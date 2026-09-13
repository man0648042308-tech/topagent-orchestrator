from __future__ import annotations

import tempfile
from pathlib import Path

from topagent.core.database import Database


class TempWorkspace:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "topagent.db")
        self.db.initialize()
        self.agents = self.root / "agents"
        self.skills = self.root / "skills"
        self.capabilities = self.root / "capabilities"
        self.artifacts = self.root / "artifacts"
        self.workspaces = self.root / "workspaces"
        self.memory_candidates = self.root / "memory" / "candidates"
        self.memory_canonical = self.root / "memory" / "canonical"
        self.memory_archive = self.root / "memory" / "archive"
        for path in (
            self.agents, self.skills, self.capabilities, self.artifacts, self.workspaces,
            self.memory_candidates, self.memory_canonical, self.memory_archive,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def add_agent(self, name: str, *, backend: str = "fake", version: str = "1.2.3") -> Path:
        path = self.agents / f"{name}.md"
        path.write_text(
            f"---\nname: {name}\ndescription: test agent\n"
            f"version: {version}\nbackend: {backend}\nmodel: test-model\n---\n\nDo the task.\n",
            encoding="utf-8",
        )
        return path

    def close(self):
        self.temp.cleanup()
