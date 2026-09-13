from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from topagent.core.database import Database, db, dump_json
from topagent.core.models import utc_now
from topagent.registry.frontmatter import parse_frontmatter
from topagent.settings import settings


@dataclass
class AgentSpec:
    agent_id: str
    description: str
    prompt_path: str
    version: str = "1.0.0"
    model: str | None = None
    backend: str = "claude"
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    def __init__(self, database: Database | None = None, root: Path | None = None):
        self.db = database or db
        self.root = root or settings.agents_dir

    def build(self) -> list[AgentSpec]:
        specs: list[AgentSpec] = []
        if not self.root.exists():
            return specs
        seen: set[str] = set()
        for path in sorted(self.root.rglob("*.md")):
            meta, _ = parse_frontmatter(path)
            agent_id = str(meta.get("name") or path.stem)
            if agent_id in seen:
                raise ValueError(f"重复 Agent ID: {agent_id}")
            seen.add(agent_id)
            description = str(meta.get("description") or "")
            content = path.read_bytes()
            version = str(meta.get("version") or "1.0.0")
            status = "deprecated" if "已废弃" in description else "active"
            spec = AgentSpec(
                agent_id=agent_id,
                description=description,
                prompt_path=str(path),
                version=version,
                model=str(meta.get("model")) if meta.get("model") else None,
                backend=str(meta.get("backend") or "claude"),
                status=status,
                metadata=meta,
            )
            self.db.execute(
                """INSERT INTO agents
                (agent_id, version, description, model, backend, prompt_path, status,
                 content_hash, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                  version=excluded.version, description=excluded.description,
                  model=excluded.model, backend=excluded.backend,
                  prompt_path=excluded.prompt_path, status=excluded.status,
                  content_hash=excluded.content_hash, metadata_json=excluded.metadata_json,
                  updated_at=excluded.updated_at""",
                (
                    spec.agent_id, spec.version, spec.description, spec.model, spec.backend,
                    spec.prompt_path, spec.status, hashlib.sha256(content).hexdigest(),
                    dump_json(meta), utc_now(),
                ),
            )
            specs.append(spec)
        for row in self.db.all("SELECT agent_id FROM agents"):
            if row["agent_id"] not in seen:
                self.db.execute("DELETE FROM agents WHERE agent_id=?", (row["agent_id"],))
        return specs

    def get(self, agent_id: str) -> AgentSpec | None:
        row = self.db.one("SELECT * FROM agents WHERE agent_id=?", (agent_id,))
        if not row:
            return None
        return AgentSpec(
            agent_id=row["agent_id"], description=row["description"],
            prompt_path=row["prompt_path"], version=row["version"], model=row["model"],
            backend=row["backend"], status=row["status"],
        )

    def list(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM agents ORDER BY agent_id")


agent_registry = AgentRegistry()
