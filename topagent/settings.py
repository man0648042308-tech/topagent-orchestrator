from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    runtime_dir: Path = ROOT / "runtime"
    database_path: Path = ROOT / "runtime" / "topagent.db"
    artifact_dir: Path = ROOT / "runtime" / "artifacts"
    workspace_dir: Path = ROOT / "runtime" / "workspaces"
    trace_dir: Path = ROOT / "runtime" / "traces"
    secret_vault_path: Path = ROOT / "runtime" / "secrets.enc"
    agents_dir: Path = ROOT / ".claude" / "agents"
    skills_dir: Path = ROOT / ".claude" / "skills"
    capabilities_dir: Path = ROOT / "system" / "capabilities"
    canonical_memory_dir: Path = ROOT / "memory" / "canonical"
    candidate_memory_dir: Path = ROOT / "memory" / "candidates"
    archive_memory_dir: Path = ROOT / "memory" / "archive"
    pipeline_file: Path = ROOT / "orchestrator" / "pipeline.json"

    def ensure_runtime(self) -> None:
        for path in (
            self.runtime_dir,
            self.artifact_dir,
            self.workspace_dir,
            self.trace_dir,
            self.capabilities_dir,
            self.canonical_memory_dir,
            self.candidate_memory_dir,
            self.archive_memory_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
