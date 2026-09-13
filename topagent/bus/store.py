from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from topagent.bus.models import LeasedMessage, Message
from topagent.core.context import current_identity
from topagent.core.database import Database, db, dump_json, load_json
from topagent.core.events import EventStore
from topagent.core.ids import new_id
from topagent.core.models import utc_now


class MessageBus:
    def __init__(self, database: Database | None = None):
        self.db = database or db
        self.events = EventStore(self.db)

    def send(self, message: Message, *, allow_legacy_sender: bool = False) -> str:
        identity = current_identity.get()
        if identity:
            sender_execution_id = identity.execution_id
            sender_agent_id = identity.agent_id
            attested = 1
        elif allow_legacy_sender and message.sender_agent_id:
            sender_execution_id = message.sender_execution_id
            sender_agent_id = message.sender_agent_id
            attested = 0
        else:
            raise PermissionError(
                "Message sender must come from an active Runtime execution identity"
            )
        now = utc_now()
        message_id = new_id("msg")
        thread_id = message.thread_id or new_id("thread")
        try:
            self.db.execute(
                """INSERT INTO messages
                (message_id, thread_id, correlation_id, causation_id,
                 sender_execution_id, sender_agent_id, recipient_agent_id,
                 message_type, priority, payload_json, idempotency_key, status,
                 attempts, max_attempts, visible_at, expires_at, created_at,
                 updated_at, attested)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id, thread_id, message.correlation_id, message.causation_id,
                    sender_execution_id, sender_agent_id, message.recipient_agent_id,
                    message.message_type, message.priority, dump_json(message.payload),
                    message.idempotency_key, message.max_attempts, now,
                    message.expires_at, now, now, attested,
                ),
            )
        except Exception as exc:
            if message.idempotency_key and "UNIQUE" in str(exc).upper():
                existing = self.db.one(
                    "SELECT message_id FROM messages WHERE idempotency_key=?",
                    (message.idempotency_key,),
                )
                if existing:
                    return existing["message_id"]
            raise
        self.events.append(
            "message.created", execution_id=sender_execution_id,
            payload={"message_id": message_id, "recipient": message.recipient_agent_id,
                     "attested": bool(attested)}, status="queued",
        )
        return message_id

    def lease(
        self, recipient_agent_id: str, worker_id: str, *, limit: int = 1,
        lease_seconds: int = 60,
    ) -> list[LeasedMessage]:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        leased: list[LeasedMessage] = []
        with self.db.transaction(immediate=True) as conn:
            rows = conn.execute(
                """SELECT * FROM messages
                WHERE recipient_agent_id=? AND status IN ('queued','retry_wait')
                  AND visible_at<=?
                  AND (expires_at IS NULL OR expires_at>?)
                ORDER BY priority ASC, created_at ASC LIMIT ?""",
                (recipient_agent_id, now, now, limit),
            ).fetchall()
            for row in rows:
                attempt = row["attempts"] + 1
                delivery_id = new_id("delivery")
                conn.execute(
                    """UPDATE messages SET status='leased', attempts=?, lease_until=?,
                    leased_by=?, updated_at=? WHERE message_id=?""",
                    (attempt, lease_until, worker_id, now, row["message_id"]),
                )
                conn.execute(
                    """INSERT INTO message_deliveries
                    (delivery_id, message_id, attempt, worker_id, status, leased_at)
                    VALUES (?, ?, ?, ?, 'leased', ?)""",
                    (delivery_id, row["message_id"], attempt, worker_id, now),
                )
                leased.append(
                    LeasedMessage(
                        message_id=row["message_id"], delivery_id=delivery_id,
                        thread_id=row["thread_id"],
                        sender_execution_id=row["sender_execution_id"],
                        sender_agent_id=row["sender_agent_id"],
                        recipient_agent_id=row["recipient_agent_id"],
                        message_type=row["message_type"],
                        payload=load_json(row["payload_json"], {}),
                        priority=row["priority"], attempts=attempt,
                        attested=bool(row["attested"]),
                    )
                )
        for item in leased:
            self.events.append(
                "message.leased", execution_id=item.sender_execution_id,
                payload={"message_id": item.message_id, "worker_id": worker_id,
                         "attempt": item.attempts}, status="leased",
            )
        return leased

    def start_processing(self, message_id: str, delivery_id: str) -> None:
        now = utc_now()
        with self.db.transaction(immediate=True) as conn:
            delivery = conn.execute(
                "SELECT 1 FROM message_deliveries WHERE delivery_id=? AND message_id=? AND status='leased'",
                (delivery_id, message_id),
            ).fetchone()
            if not delivery:
                raise PermissionError("delivery_id 与消息租约不匹配")
            conn.execute(
                """UPDATE messages SET status='processing', updated_at=?
                WHERE message_id=? AND status='leased'""", (now, message_id),
            )
            conn.execute(
                "UPDATE message_deliveries SET status='processing' WHERE delivery_id=?",
                (delivery_id,),
            )

    def acknowledge(self, message_id: str, delivery_id: str, *, completed: bool = True) -> None:
        now = utc_now()
        status = "completed" if completed else "acknowledged"
        with self.db.transaction(immediate=True) as conn:
            delivery = conn.execute(
                """SELECT 1 FROM message_deliveries WHERE delivery_id=? AND message_id=?
                AND status IN ('leased','processing')""", (delivery_id, message_id),
            ).fetchone()
            if not delivery:
                raise PermissionError("delivery_id 与消息租约不匹配或已结束")
            conn.execute(
                """UPDATE messages SET status=?, acknowledged_at=?, completed_at=?,
                lease_until=NULL, leased_by=NULL, updated_at=? WHERE message_id=?""",
                (status, now, now if completed else None, now, message_id),
            )
            conn.execute(
                "UPDATE message_deliveries SET status=?, finished_at=? WHERE delivery_id=?",
                (status, now, delivery_id),
            )
        self.events.append(
            f"message.{status}", payload={"message_id": message_id}, status=status
        )

    def fail(self, message_id: str, delivery_id: str, error: str, *, retry_delay: int = 5) -> str:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self.db.transaction(immediate=True) as conn:
            delivery = conn.execute(
                """SELECT 1 FROM message_deliveries WHERE delivery_id=? AND message_id=?
                AND status IN ('leased','processing')""", (delivery_id, message_id),
            ).fetchone()
            if not delivery:
                raise PermissionError("delivery_id 与消息租约不匹配或已结束")
            row = conn.execute(
                "SELECT attempts, max_attempts FROM messages WHERE message_id=?",
                (message_id,),
            ).fetchone()
            if not row:
                raise KeyError(message_id)
            if row["attempts"] >= row["max_attempts"]:
                status = "dead_letter"
                visible_at = now
            else:
                status = "retry_wait"
                visible_at = (now_dt + timedelta(seconds=retry_delay)).isoformat()
            conn.execute(
                """UPDATE messages SET status=?, visible_at=?, lease_until=NULL,
                leased_by=NULL, last_error=?, updated_at=? WHERE message_id=?""",
                (status, visible_at, error, now, message_id),
            )
            conn.execute(
                """UPDATE message_deliveries SET status='failed', finished_at=?, error=?
                WHERE delivery_id=?""", (now, error, delivery_id),
            )
        self.events.append(
            "message.failed", payload={"message_id": message_id, "error": error,
                                       "next_status": status}, status=status,
        )
        return status

    def requeue_expired(self) -> int:
        now = utc_now()
        rows = self.db.all(
            "SELECT message_id FROM messages WHERE status IN ('leased','processing') AND lease_until<?",
            (now,),
        )
        for row in rows:
            with self.db.transaction(immediate=True) as conn:
                conn.execute(
                    """UPDATE messages SET status='queued', leased_by=NULL, lease_until=NULL,
                    visible_at=?, updated_at=?, last_error='lease expired' WHERE message_id=?""",
                    (now, now, row["message_id"]),
                )
                conn.execute(
                    """UPDATE message_deliveries SET status='expired', finished_at=?,
                    error='lease expired' WHERE message_id=? AND status IN ('leased','processing')""",
                    (now, row["message_id"]),
                )
        return len(rows)

    def list(self, *, recipient_agent_id: str | None = None, status: str | None = None,
             limit: int = 100) -> list[dict[str, Any]]:
        clauses, params = [], []
        if recipient_agent_id:
            clauses.append("recipient_agent_id=?")
            params.append(recipient_agent_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = self.db.all(
            f"SELECT * FROM messages{where} ORDER BY created_at DESC LIMIT ?", params
        )
        for row in rows:
            row["payload"] = load_json(row.pop("payload_json"), {})
        return rows

    def stats(self) -> dict[str, int]:
        rows = self.db.all("SELECT status, COUNT(*) AS count FROM messages GROUP BY status")
        values = {row["status"]: row["count"] for row in rows}
        values["total"] = sum(values.values())
        return values


message_bus = MessageBus()
