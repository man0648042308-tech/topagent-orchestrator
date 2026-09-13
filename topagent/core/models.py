from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    sha256: str
    media_type: str
    path: str
    size_bytes: int


@dataclass
class ExecutionConstraints:
    timeout_seconds: int = 300
    max_turns: int = 10
    workspace_mode: str = "shared"
    # 质量优先：默认允许需要计费或消耗订阅额度的执行器。
    # 调用方仍可显式设为 False，进入 free-only 模式。
    allow_paid_calls: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionRequest:
    agent_id: str
    task: str
    inputs: list[ArtifactRef] = field(default_factory=list)
    constraints: ExecutionConstraints = field(default_factory=ExecutionConstraints)
    parent_execution_id: str | None = None
    run_id: str | None = None


@dataclass
class ExecutionHandle:
    execution_id: str
    agent_id: str
    backend: str
    model: str | None
    status: str
    trace_id: str


@dataclass
class ExecutionResult:
    execution_id: str
    agent_id: str
    agent_version: str
    backend: str
    model: str | None
    status: str
    structured_output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    verifier_identity: dict[str, Any] | None = None
    attestation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
