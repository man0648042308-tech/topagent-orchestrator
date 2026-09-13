from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionIdentity:
    execution_id: str
    agent_id: str
    agent_version: str = "unknown"
    backend: str = "unknown"
    model: str | None = None


current_identity: ContextVar[ExecutionIdentity | None] = ContextVar(
    "topagent_execution_identity", default=None
)


@contextmanager
def execution_identity(identity: ExecutionIdentity):
    token = current_identity.set(identity)
    try:
        yield identity
    finally:
        current_identity.reset(token)
