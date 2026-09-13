from __future__ import annotations

import hashlib
import json
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from topagent.artifacts import ArtifactStore
from topagent.core.context import ExecutionIdentity, execution_identity
from topagent.core.database import Database, db, dump_json
from topagent.core.events import EventStore
from topagent.core.ids import new_id
from topagent.core.models import (
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
    utc_now,
)
from topagent.registry.agents import AgentRegistry
from topagent.runtime.executors import (
    ClaudeCodeExecutor,
    CodexExecutor,
    Executor,
    ExecutorOutput,
    FakeExecutor,
    RouterExecutor,
    SubprocessExecutor,
)
from topagent.settings import settings


class Dispatcher:
    """统一执行入口：把 Agent 字符串解析为可审计的真实执行。"""

    def __init__(
        self,
        *,
        database: Database | None = None,
        registry: AgentRegistry | None = None,
        artifact_store: ArtifactStore | None = None,
        workspace_root: Path | None = None,
        max_workers: int = 4,
    ):
        self.db = database or db
        self.db.initialize()
        self.registry = registry or AgentRegistry(self.db)
        self.artifacts = artifact_store or ArtifactStore(self.db)
        self.events = EventStore(self.db)
        self.workspace_root = workspace_root or settings.workspace_dir
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.executors: dict[str, Executor] = {}
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="topagent")
        for executor in (
            FakeExecutor(),
            SubprocessExecutor(),
            ClaudeCodeExecutor(),
            CodexExecutor(),
            RouterExecutor(),
        ):
            self.register_executor(executor)

    def register_executor(self, executor: Executor) -> None:
        self.executors[executor.backend] = executor

    def dispatch(self, request: ExecutionRequest) -> ExecutionResult:
        agent = self.registry.get(request.agent_id)
        if agent is None:
            self.registry.build()
            agent = self.registry.get(request.agent_id)
        if agent is None:
            raise KeyError(f"未注册 Agent: {request.agent_id}")
        if agent.status != "active":
            raise RuntimeError(f"Agent {agent.agent_id} 状态为 {agent.status}，不可执行")
        executor = self.executors.get(agent.backend)
        if executor is None:
            raise KeyError(f"未注册 Executor backend: {agent.backend}")
        verification_subject = request.constraints.metadata.get(
            "verification_subject_execution_id"
        )
        if verification_subject:
            subject = self.db.one(
                "SELECT execution_id, agent_id FROM executions WHERE execution_id=?",
                (verification_subject,),
            )
            if not subject:
                raise KeyError(f"待验证 execution 不存在: {verification_subject}")
            if subject["agent_id"] == agent.agent_id:
                raise PermissionError("生产者与验证者 agent_id 必须不同")

        execution_id = new_id("exe")
        trace_id = new_id("trc")
        created_at = utc_now()
        input_record = {
            "task": request.task,
            "inputs": [item.sha256 for item in request.inputs],
            "constraints": request.constraints.__dict__,
        }
        input_hash = self._hash(input_record)
        self.db.execute(
            """INSERT INTO executions
            (execution_id, run_id, parent_execution_id, agent_id, agent_version,
             backend, model, task, status, trace_id, input_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (
                execution_id,
                request.run_id,
                request.parent_execution_id,
                agent.agent_id,
                agent.version,
                agent.backend,
                agent.model,
                request.task,
                trace_id,
                input_hash,
                created_at,
            ),
        )
        self.events.append(
            "execution.queued",
            execution_id=execution_id,
            run_id=request.run_id,
            trace_id=trace_id,
            status="queued",
            payload={"agent_id": agent.agent_id, "input_hash": input_hash},
        )
        workspace = self.workspace_root / execution_id
        workspace.mkdir(parents=True, exist_ok=False)
        started_at = utc_now()
        self.db.execute(
            "UPDATE executions SET status='running', started_at=? WHERE execution_id=?",
            (started_at, execution_id),
        )
        self.events.append(
            "execution.started",
            execution_id=execution_id,
            run_id=request.run_id,
            trace_id=trace_id,
            status="running",
            payload={"backend": agent.backend, "workspace": str(workspace)},
        )

        identity = ExecutionIdentity(
            execution_id=execution_id,
            agent_id=agent.agent_id,
            agent_version=agent.version,
            backend=agent.backend,
            model=agent.model,
        )
        try:
            with execution_identity(identity):
                output = executor.execute(request, agent, workspace)
            if verification_subject:
                output.verifier_identity = {
                    "execution_id": execution_id,
                    "agent_id": agent.agent_id,
                    "agent_version": agent.version,
                    "backend": agent.backend,
                    "model": agent.model,
                    "subject_execution_id": verification_subject,
                }
            return self._complete(
                request, agent, execution_id, trace_id, input_hash, output
            )
        except Exception as exc:
            return self._fail(request, agent, execution_id, trace_id, input_hash, exc)

    def verify(
        self,
        *,
        verifier_agent_id: str,
        subject_execution_id: str,
        task: str,
        constraints=None,
    ) -> ExecutionResult:
        """独立验证入口；强制生产者与验证者 Agent 不同。"""
        from topagent.core.models import ExecutionConstraints

        effective = constraints or ExecutionConstraints()
        effective.metadata = {
            **effective.metadata,
            "verification_subject_execution_id": subject_execution_id,
            "role": "verifier",
        }
        subject = self.db.one(
            "SELECT run_id FROM executions WHERE execution_id=?",
            (subject_execution_id,),
        )
        return self.dispatch(
            ExecutionRequest(
                agent_id=verifier_agent_id,
                task=task,
                parent_execution_id=subject_execution_id,
                run_id=subject["run_id"] if subject else None,
                constraints=effective,
            )
        )

    def submit(self, request: ExecutionRequest) -> tuple[ExecutionHandle, Future[ExecutionResult]]:
        """异步入口。Handle 在任务启动后由 Future 结果提供最终身份。"""
        future = self.pool.submit(self.dispatch, request)
        handle = ExecutionHandle(
            execution_id="pending",
            agent_id=request.agent_id,
            backend="pending",
            model=None,
            status="submitted",
            trace_id="pending",
        )
        return handle, future

    def _complete(
        self, request, agent, execution_id: str, trace_id: str,
        input_hash: str, output: ExecutorOutput,
    ) -> ExecutionResult:
        artifact_refs = []
        result_artifact = self.artifacts.put_json(
            output.structured_output,
            execution_id=execution_id,
            metadata={"kind": "structured-result"},
        )
        artifact_refs.append(result_artifact)
        for path_value, media_type in output.produced_files:
            artifact_refs.append(
                self.artifacts.import_file(
                    path_value, media_type=media_type, execution_id=execution_id
                )
            )
        output_hash = self._hash(
            {
                "structured_output": output.structured_output,
                "artifacts": [item.sha256 for item in artifact_refs],
            }
        )
        attestation = {
            "issuer": "topagent-runtime",
            "execution_id": execution_id,
            "agent_id": agent.agent_id,
            "agent_version": agent.version,
            "backend": agent.backend,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "attested_at": utc_now(),
        }
        ended_at = utc_now()
        self.db.execute(
            """UPDATE executions SET status=?, output_hash=?, ended_at=?,
               metrics_json=?, attestation_json=?, verifier_identity_json=?
               WHERE execution_id=?""",
            (
                output.status,
                output_hash,
                ended_at,
                dump_json(output.metrics),
                dump_json(attestation),
                dump_json(output.verifier_identity) if output.verifier_identity else None,
                execution_id,
            ),
        )
        self.events.append(
            "execution.completed",
            execution_id=execution_id,
            run_id=request.run_id,
            trace_id=trace_id,
            status=output.status,
            payload={
                "output_hash": output_hash,
                "artifact_ids": [item.artifact_id for item in artifact_refs],
                "verifier_identity": output.verifier_identity,
            },
        )
        return ExecutionResult(
            execution_id=execution_id,
            agent_id=agent.agent_id,
            agent_version=agent.version,
            backend=agent.backend,
            model=agent.model,
            status=output.status,
            structured_output=output.structured_output,
            artifacts=artifact_refs,
            metrics=output.metrics,
            verifier_identity=output.verifier_identity,
            attestation=attestation,
        )

    def _fail(
        self, request, agent, execution_id: str, trace_id: str,
        input_hash: str, exc: Exception,
    ) -> ExecutionResult:
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": "".join(traceback.format_exception(exc))[-8000:],
        }
        attestation = {
            "issuer": "topagent-runtime",
            "execution_id": execution_id,
            "agent_id": agent.agent_id,
            "agent_version": agent.version,
            "backend": agent.backend,
            "input_hash": input_hash,
            "attested_at": utc_now(),
        }
        self.db.execute(
            """UPDATE executions SET status='failed', ended_at=?, error_json=?,
               attestation_json=? WHERE execution_id=?""",
            (utc_now(), dump_json(error), dump_json(attestation), execution_id),
        )
        self.events.append(
            "execution.failed",
            execution_id=execution_id,
            run_id=request.run_id,
            trace_id=trace_id,
            status="failed",
            payload=error,
        )
        return ExecutionResult(
            execution_id=execution_id,
            agent_id=agent.agent_id,
            agent_version=agent.version,
            backend=agent.backend,
            model=agent.model,
            status="failed",
            error=error,
            attestation=attestation,
        )

    @staticmethod
    def _hash(value: Any) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
