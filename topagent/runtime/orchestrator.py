from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from topagent.core.database import Database, db, dump_json
from topagent.core.ids import new_id
from topagent.core.models import ExecutionConstraints, ExecutionRequest, utc_now
from topagent.runtime.dispatcher import Dispatcher
from topagent.settings import settings


@dataclass
class StepResult:
    run_id: str
    step_id: str
    status: str
    executions: list[dict[str, Any]]
    gate: dict[str, Any]


class RuntimeOrchestrator:
    """pipeline.json 的可执行适配层。

    旧编排器仍负责人工门禁；本类负责把 spawn 中的 Agent 字符串变成
    数据库可验证的 execution，并将 execution_id/trace/产物写入统一存储。
    """

    def __init__(
        self,
        *,
        database: Database | None = None,
        dispatcher: Dispatcher | None = None,
        pipeline_file: Path | None = None,
    ):
        self.db = database or db
        self.db.initialize()
        self.dispatcher = dispatcher or Dispatcher(database=self.db)
        self.pipeline_file = pipeline_file or settings.pipeline_file

    def pipeline(self) -> dict[str, Any]:
        return json.loads(self.pipeline_file.read_text(encoding="utf-8-sig"))

    def create_run(
        self, requirement: str, *, metadata: dict[str, Any] | None = None
    ) -> str:
        pipeline = self.pipeline()
        run_id = new_id("run")
        now = utc_now()
        first_step = pipeline["steps_order"][0]
        self.db.execute(
            """INSERT INTO runs
            (run_id, requirement, pipeline_version, status, current_step,
             created_at, updated_at, metadata_json)
            VALUES (?, ?, ?, 'created', ?, ?, ?, ?)""",
            (
                run_id,
                requirement,
                str(pipeline.get("version", "unknown")),
                first_step,
                now,
                now,
                dump_json(metadata or {}),
            ),
        )
        return run_id

    def run_step(
        self,
        run_id: str,
        step_id: str,
        *,
        allow_paid_calls: bool = True,
        timeout_seconds: int = 300,
        shared_inputs: dict[str, Any] | None = None,
    ) -> StepResult:
        pipeline = self.pipeline()
        if step_id not in pipeline["steps"]:
            raise KeyError(f"未知 pipeline step: {step_id}")
        if not self.db.one("SELECT run_id FROM runs WHERE run_id=?", (run_id,)):
            raise KeyError(f"未知 run: {run_id}")
        definition = pipeline["steps"][step_id]
        self.db.execute(
            "UPDATE runs SET status='running', current_step=?, updated_at=? WHERE run_id=?",
            (step_id, utc_now(), run_id),
        )
        results: list[dict[str, Any]] = []
        for spawn in definition.get("spawn", []):
            task = str(spawn.get("task") or definition.get("desc") or "")
            context = {
                "pipeline_step": step_id,
                "declared_inputs": spawn.get("inputs", []),
                "declared_outputs": spawn.get("outputs", []),
                "shared_inputs": shared_inputs or {},
            }
            request = ExecutionRequest(
                agent_id=str(spawn["agent"]),
                task=task,
                run_id=run_id,
                constraints=ExecutionConstraints(
                    timeout_seconds=timeout_seconds,
                    allow_paid_calls=allow_paid_calls,
                    metadata=context,
                ),
            )
            result = self.dispatcher.dispatch(request)
            results.append(result.to_dict())
        status = "awaiting_gate"
        if any(item["status"] != "succeeded" for item in results):
            status = "failed"
        elif definition.get("gate", {}).get("type") == "none":
            status = "succeeded"
        self.db.execute(
            "UPDATE runs SET status=?, updated_at=? WHERE run_id=?",
            (status, utc_now(), run_id),
        )
        return StepResult(
            run_id=run_id,
            step_id=step_id,
            status=status,
            executions=results,
            gate=definition.get("gate", {}),
        )

    def status(self, run_id: str) -> dict[str, Any] | None:
        run = self.db.one("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if not run:
            return None
        run["metadata"] = json.loads(run.pop("metadata_json"))
        run["executions"] = self.db.all(
            "SELECT * FROM executions WHERE run_id=? ORDER BY created_at", (run_id,)
        )
        return run
