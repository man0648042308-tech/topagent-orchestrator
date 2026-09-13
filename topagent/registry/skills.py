from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from topagent.core.database import Database, db, dump_json
from topagent.core.models import utc_now
from topagent.registry.frontmatter import parse_frontmatter
from topagent.settings import settings


@dataclass
class SkillSpec:
    skill_id: str
    description: str
    skill_path: str
    version: str = "1.0.0"
    status: str = "active"


class SkillRegistry:
    def __init__(self, database: Database | None = None, root: Path | None = None):
        self.db = database or db
        self.root = root or settings.skills_dir

    def build(self) -> list[SkillSpec]:
        paths = list(self.root.rglob("SKILL.md")) if self.root.exists() else []
        paths += [p for p in self.root.glob("*.md") if p.name != "SKILL.md"] if self.root.exists() else []
        specs: list[SkillSpec] = []
        seen: set[str] = set()
        for path in sorted(set(paths)):
            meta, _ = parse_frontmatter(path)
            skill_id = str(meta.get("name") or path.parent.name or path.stem)
            if skill_id in seen:
                raise ValueError(f"重复 Skill ID: {skill_id}")
            seen.add(skill_id)
            description = str(meta.get("description") or "")
            status = "deprecated" if "已废弃" in description else "active"
            version = str(meta.get("version") or "1.0.0")
            content = path.read_bytes()
            self.db.execute(
                """INSERT INTO skills
                (skill_id, version, description, skill_path, status, content_hash,
                 metadata_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET
                  version=excluded.version, description=excluded.description,
                  skill_path=excluded.skill_path, status=excluded.status,
                  content_hash=excluded.content_hash, metadata_json=excluded.metadata_json,
                  updated_at=excluded.updated_at""",
                (
                    skill_id, version, description, str(path), status,
                    hashlib.sha256(content).hexdigest(), dump_json(meta), utc_now(),
                ),
            )
            specs.append(SkillSpec(skill_id, description, str(path), version, status))
        for row in self.db.all("SELECT skill_id FROM skills"):
            if row["skill_id"] not in seen:
                self.db.execute("DELETE FROM skills WHERE skill_id=?", (row["skill_id"],))
        return specs

    def metadata(self) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT skill_id, version, description, status, skill_path, updated_at FROM skills ORDER BY skill_id"
        )

    def list(self) -> list[dict[str, Any]]:
        return self.metadata()

    def load_instructions(self, skill_id: str) -> str:
        row = self.db.one("SELECT skill_path FROM skills WHERE skill_id=?", (skill_id,))
        if not row:
            raise KeyError(f"Unknown skill: {skill_id}")
        return Path(row["skill_path"]).read_text(encoding="utf-8-sig", errors="replace")


skill_registry = SkillRegistry()
