from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    recipient_agent_id: str
    message_type: str
    payload: dict[str, Any]
    thread_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    priority: int = 2
    idempotency_key: str | None = None
    max_attempts: int = 3
    expires_at: str | None = None
    sender_execution_id: str | None = None
    sender_agent_id: str | None = None


@dataclass
class LeasedMessage:
    message_id: str
    delivery_id: str
    thread_id: str
    sender_execution_id: str | None
    sender_agent_id: str
    recipient_agent_id: str
    message_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 2
    attempts: int = 1
    attested: bool = False
