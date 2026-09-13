from __future__ import annotations

from typing import Any

from topagent.bus.models import Message
from topagent.bus.store import MessageBus, message_bus


class BusService:
    """Stable application boundary used by MCP, CLI and the scheduler."""

    def __init__(self, bus: MessageBus | None = None):
        self.bus = bus or message_bus

    def send(self, params: dict[str, Any], *, legacy: bool = False) -> dict[str, Any]:
        recipient = params.get("recipient_agent_id") or params.get("to")
        if not recipient:
            raise ValueError("recipient_agent_id is required")
        payload = params.get("payload") or params.get("body") or {}
        message_id = self.bus.send(
            Message(
                recipient_agent_id=recipient,
                message_type=params.get("message_type") or params.get("type") or "notification",
                payload=payload,
                thread_id=params.get("thread_id"),
                correlation_id=params.get("correlation_id"),
                causation_id=params.get("causation_id"),
                priority=int(params.get("priority", 2)) if str(params.get("priority", 2)).isdigit() else 2,
                idempotency_key=params.get("idempotency_key"),
                max_attempts=int(params.get("max_attempts", 3)),
                expires_at=params.get("expires_at"),
                sender_execution_id=params.get("sender_execution_id"),
                sender_agent_id=params.get("sender_agent_id") or params.get("from"),
            ),
            allow_legacy_sender=legacy,
        )
        return {"ok": True, "message_id": message_id}

    def lease(self, params: dict[str, Any]) -> dict[str, Any]:
        agent = params.get("recipient_agent_id") or params.get("agent")
        worker = params.get("worker_id") or f"mcp-{agent}"
        if not agent:
            raise ValueError("recipient_agent_id is required")
        messages = self.bus.lease(
            agent, worker, limit=int(params.get("limit", 10)),
            lease_seconds=int(params.get("lease_seconds", 60)),
        )
        return {"ok": True, "count": len(messages), "messages": [m.__dict__ for m in messages]}


bus_service = BusService()
