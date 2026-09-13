from __future__ import annotations

import unittest

from topagent.artifacts import ArtifactStore
from topagent.bus.models import Message
from topagent.bus.store import MessageBus
from topagent.registry.agents import AgentRegistry
from topagent.runtime.dispatcher import Dispatcher
from topagent.runtime.scheduler import Scheduler
from tests.helpers import TempWorkspace


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempWorkspace()
        self.temp.add_agent("worker")
        registry = AgentRegistry(self.temp.db, self.temp.agents)
        registry.build()
        self.bus = MessageBus(self.temp.db)
        dispatcher = Dispatcher(
            database=self.temp.db, registry=registry,
            artifact_store=ArtifactStore(self.temp.db, self.temp.artifacts),
            workspace_root=self.temp.workspaces,
        )
        self.scheduler = Scheduler(
            database=self.temp.db, bus=self.bus, dispatcher=dispatcher,
            worker_id="test-scheduler",
        )

    def tearDown(self):
        self.temp.close()

    def test_message_is_dispatched_acknowledged_and_visible_in_presence(self):
        self.bus.send(
            Message(
                recipient_agent_id="worker", message_type="task",
                payload={"task": "execute from queue"}, sender_agent_id="legacy",
            ),
            allow_legacy_sender=True,
        )
        result = self.scheduler.tick("worker")
        self.assertEqual(1, result.succeeded)
        self.assertEqual("completed", self.bus.list()[0]["status"])
        execution = self.temp.db.one("SELECT * FROM executions")
        self.assertEqual("succeeded", execution["status"])
        presence = self.temp.db.one("SELECT * FROM agent_presence")
        self.assertEqual("idle", presence["state"])


if __name__ == "__main__":
    unittest.main()
