from __future__ import annotations

import re
from dataclasses import dataclass

from topagent.registry.skills import SkillRegistry


@dataclass
class SkillMatch:
    skill_id: str
    score: int
    description: str
    version: str


class ProgressiveSkillLoader:
    """Level 1 元数据筛选；只有选中的 Skill 才进入 Level 2 全文加载。"""

    def __init__(self, registry: SkillRegistry | None = None):
        self.registry = registry or SkillRegistry()

    def match(self, task: str, *, limit: int = 5) -> list[SkillMatch]:
        task_tokens = self._tokens(task)
        matches: list[SkillMatch] = []
        for item in self.registry.list():
            haystack = self._tokens(f"{item['skill_id']} {item['description']}")
            overlap = len(task_tokens & haystack)
            if overlap:
                matches.append(
                    SkillMatch(
                        skill_id=item["skill_id"], score=overlap,
                        description=item["description"], version=item["version"],
                    )
                )
        return sorted(matches, key=lambda item: (-item.score, item.skill_id))[:limit]

    def load_selected(self, task: str, *, limit: int = 3) -> dict[str, str]:
        return {
            match.skill_id: self.registry.load_instructions(match.skill_id)
            for match in self.match(task, limit=limit)
        }

    @staticmethod
    def _tokens(value: str) -> set[str]:
        lowered = value.lower()
        latin = set(re.findall(r"[a-z0-9_-]{2,}", lowered))
        chinese = {
            lowered[index:index + 2]
            for index in range(max(0, len(lowered) - 1))
            if "\u4e00" <= lowered[index] <= "\u9fff"
            and "\u4e00" <= lowered[index + 1] <= "\u9fff"
        }
        return latin | chinese
