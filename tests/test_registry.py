from __future__ import annotations

import json
import unittest

from topagent.registry.agents import AgentRegistry
from topagent.registry.builder import build_all
from topagent.registry.selector import ProgressiveSkillLoader
from topagent.registry.skills import SkillRegistry
from tests.helpers import TempWorkspace


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempWorkspace()

    def tearDown(self):
        self.temp.close()

    def test_builds_source_of_truth_and_progressively_loads_skill(self):
        self.temp.add_agent("builder")
        skill_dir = self.temp.skills / "database-tuning"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: database-tuning\ndescription: Tune SQLite database indexes\n"
            "version: 2.0.0\n---\n\n# Full secret instructions\n",
            encoding="utf-8",
        )
        contract = {
            "capability_id": "test", "name": "Test", "status": "implemented",
            "maturity": "L1", "owner": "tests",
        }
        (self.temp.capabilities / "test.json").write_text(json.dumps(contract), encoding="utf-8")
        summary = build_all(
            self.temp.db, agents_root=self.temp.agents, skills_root=self.temp.skills,
            capabilities_root=self.temp.capabilities,
        )
        self.assertEqual({"agents": 1, "skills": 1, "capabilities": 1}, summary)
        skills = SkillRegistry(self.temp.db, self.temp.skills)
        loader = ProgressiveSkillLoader(skills)
        matches = loader.match("Please tune our SQLite database")
        self.assertEqual("database-tuning", matches[0].skill_id)
        self.assertIn("Full secret instructions", loader.load_selected("SQLite database")["database-tuning"])


if __name__ == "__main__":
    unittest.main()
