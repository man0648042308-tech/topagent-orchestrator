from __future__ import annotations

import json
import unittest

from topagent.artifacts import ArtifactStore
from topagent.registry.agents import AgentRegistry
from topagent.runtime.dispatcher import Dispatcher
from topagent.runtime.orchestrator import RuntimeOrchestrator
from tests.helpers import TempWorkspace


class OrchestratorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempWorkspace()
        self.temp.add_agent("worker")
        registry = AgentRegistry(self.temp.db, self.temp.agents)
        registry.build()
        dispatcher = Dispatcher(
            database=self.temp.db, registry=registry,
            artifact_store=ArtifactStore(self.temp.db, self.temp.artifacts),
            workspace_root=self.temp.workspaces,
        )
        pipeline = {
            "version": "test", "steps_order": ["step_1"],
            "steps": {"step_1": {
                "name": "execute", "spawn": [{"agent": "worker", "task": "build"}],
                "gate": {"type": "none"},
            }},
        }
        pipeline_path = self.temp.root / "pipeline.json"
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        self.orchestrator = RuntimeOrchestrator(
            database=self.temp.db, dispatcher=dispatcher, pipeline_file=pipeline_path
        )

    def tearDown(self):
        self.temp.close()

    def test_pipeline_agent_string_becomes_execution(self):
        run_id = self.orchestrator.create_run("test requirement")
        result = self.orchestrator.run_step(run_id, "step_1")
        self.assertEqual("succeeded", result.status)
        self.assertTrue(result.executions[0]["execution_id"].startswith("exe-"))
        status = self.orchestrator.status(run_id)
        self.assertEqual(1, len(status["executions"]))


if __name__ == "__main__":
    unittest.main()
