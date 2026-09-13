from __future__ import annotations

import unittest

from topagent.memory.store import MemoryStore
from tests.helpers import TempWorkspace


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempWorkspace()
        self.memory = MemoryStore(
            self.temp.db,
            candidate_dir=self.temp.memory_candidates,
            canonical_dir=self.temp.memory_canonical,
            archive_dir=self.temp.memory_archive,
        )

    def tearDown(self):
        self.temp.close()

    def test_candidate_promote_search_archive(self):
        candidate = self.memory.add_candidate(
            namespace="project", memory_type="decision", subject="Queue backend",
            content="SQLite WAL is the local durable queue.", confidence=0.9,
            tags=["sqlite", "queue"],
        )
        self.assertTrue(list(self.temp.memory_candidates.glob("*.md")))
        active = self.memory.promote(candidate.memory_id, verified_by="qa")
        self.assertEqual("active", active.status)
        self.assertEqual(candidate.memory_id, self.memory.search("SQLite queue")[0].memory_id)
        archived = self.memory.archive(candidate.memory_id, actor="qa", reason="obsolete")
        self.assertEqual("archived", archived.status)
        self.assertEqual([], self.memory.search("SQLite queue"))

    def test_conflict_requires_explicit_supersede(self):
        first = self.memory.add_candidate(
            namespace="project", memory_type="fact", subject="Port",
            content="The service port is 8000.", confidence=0.8,
        )
        self.memory.promote(first.memory_id, verified_by="qa")
        second = self.memory.add_candidate(
            namespace="project", memory_type="fact", subject="Port",
            content="The service port is 8765.", confidence=0.9,
        )
        conflict = self.memory.promote(second.memory_id, verified_by="qa")
        self.assertEqual("conflict", conflict.status)
        resolved = self.memory.promote(
            second.memory_id, verified_by="human", supersede_existing=True
        )
        self.assertEqual("active", resolved.status)
        self.assertEqual("superseded", self.memory.get(first.memory_id).status)


if __name__ == "__main__":
    unittest.main()
