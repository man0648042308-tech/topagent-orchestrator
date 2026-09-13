from __future__ import annotations

from pathlib import Path

from topagent.core.database import Database
from topagent.registry.agents import AgentRegistry
from topagent.registry.capabilities import CapabilityRegistry
from topagent.registry.skills import SkillRegistry


def build_all(
    database: Database | None = None,
    *,
    agents_root: Path | None = None,
    skills_root: Path | None = None,
    capabilities_root: Path | None = None,
) -> dict[str, int]:
    return {
        "agents": len(AgentRegistry(database, agents_root).build()),
        "skills": len(SkillRegistry(database, skills_root).build()),
        "capabilities": len(CapabilityRegistry(database, capabilities_root).build()),
    }
