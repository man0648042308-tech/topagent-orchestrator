from __future__ import annotations

from typing import Any

from topagent.core.database import Database, db, dump_json
from topagent.core.ids import new_id
from topagent.core.models import utc_now


class EventStore:
    def __init__(self, database: Database | None = None):
        self.db = database or db

    def append(
        self,
        event_type: str,
        *,
        execution_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        parent_event_id: str | None = None,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_id = new_id("evt")
        self.db.execute(
            """INSERT INTO execution_events
            (event_id, execution_id, run_id, trace_id, parent_event_id,
             event_type, status, occurred_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                execution_id,
                run_id,
                trace_id,
                parent_event_id,
                event_type,
                status,
                utc_now(),
                dump_json(payload or {}),
            ),
        )
        return event_id

    def list(self, *, execution_id: str | None = None, limit: int = 200):
        if execution_id:
            return self.db.all(
                "SELECT * FROM execution_events WHERE execution_id=? ORDER BY occurred_at LIMIT ?",
                (execution_id, limit),
            )
        return self.db.all(
            "SELECT * FROM execution_events ORDER BY occurred_at DESC LIMIT ?", (limit,)
        )


events = EventStore()
