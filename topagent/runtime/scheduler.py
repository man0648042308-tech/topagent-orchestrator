from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any

from topagent.bus.store import MessageBus
from topagent.core.database import Database, db, dump_json
from topagent.core.models import ExecutionConstraints, ExecutionRequest, utc_now
from topagent.runtime.dispatcher import Dispatcher


@dataclass
class SchedulerTick:
    leased: int = 0
    succeeded: int = 0
    failed: int = 0


class Scheduler:
    """把持久消息变成实际执行；一次 tick 可安全地由外部循环反复调用。"""

    def __init__(
        self,
        *,
        database: Database | None = None,
        bus: MessageBus | None = None,
        dispatcher: Dispatcher | None = None,
        worker_id: str | None = None,
    ):
        self.db = database or db
        self.db.initialize()
        self.bus = bus or MessageBus(self.db)
        self.dispatcher = dispatcher or Dispatcher(database=self.db)
        self.worker_id = worker_id or f"scheduler@{socket.gethostname()}"

    def tick(self, agent_id: str, *, limit: int = 1) -> SchedulerTick:
        self.heartbeat(agent_id, "idle")
        leased = self.bus.lease(agent_id, self.worker_id, limit=limit)
        stats = SchedulerTick(leased=len(leased))
        for item in leased:
            self.bus.start_processing(item.message_id, item.delivery_id)
            payload: dict[str, Any] = item.payload
            self.heartbeat(agent_id, "running", payload.get("execution_id"))
            constraints_data = payload.get("constraints") or {}
            request = ExecutionRequest(
                agent_id=agent_id,
                task=str(payload.get("task") or payload.get("content") or ""),
                constraints=ExecutionConstraints(**{
                    key: value for key, value in constraints_data.items()
                    if key in ExecutionConstraints.__dataclass_fields__
                }),
                parent_execution_id=item.sender_execution_id,
                run_id=payload.get("run_id"),
            )
            result = self.dispatcher.dispatch(request)
            if result.status == "succeeded":
                self.bus.acknowledge(item.message_id, item.delivery_id)
                stats.succeeded += 1
            else:
                self.bus.fail(
                    item.message_id,
                    item.delivery_id,
                    (result.error or {}).get("message", "execution failed"),
                )
                stats.failed += 1
        self.heartbeat(agent_id, "idle")
        return stats

    def heartbeat(
        self, agent_id: str, state: str, execution_id: str | None = None
    ) -> None:
        self.db.execute(
            """INSERT INTO agent_presence
            (agent_id, worker_id, state, current_execution_id, last_heartbeat_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, worker_id) DO UPDATE SET
              state=excluded.state,
              current_execution_id=excluded.current_execution_id,
              last_heartbeat_at=excluded.last_heartbeat_at,
              metadata_json=excluded.metadata_json""",
            (agent_id, self.worker_id, state, execution_id, utc_now(), dump_json({})),
        )
