from __future__ import annotations

import unittest

from topagent.artifacts import ArtifactStore
from topagent.bus.models import Message
from topagent.bus.store import MessageBus
from topagent.core.models import ExecutionConstraints, ExecutionRequest
from topagent.registry.agents import AgentRegistry
from topagent.runtime.dispatcher import Dispatcher
from topagent.runtime.executors import ExecutorOutput
from tests.helpers import TempWorkspace


class MessagingExecutor:
    backend = "messaging"

    def __init__(self, bus: MessageBus):
        self.bus = bus

    def execute(self, request, agent, workspace):
        message_id = self.bus.send(
            Message(
                recipient_agent_id="reviewer",
                message_type="review.requested",
                payload={"task": request.task},
            )
        )
        return ExecutorOutput(structured_output={"message_id": message_id})


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempWorkspace()

    def tearDown(self):
        self.temp.close()

    def dispatcher(self, agent_name: str, backend: str = "fake") -> Dispatcher:
        self.temp.add_agent(agent_name, backend=backend)
        registry = AgentRegistry(self.temp.db, self.temp.agents)
        registry.build()
        return Dispatcher(
            database=self.temp.db,
            registry=registry,
            artifact_store=ArtifactStore(self.temp.db, self.temp.artifacts),
            workspace_root=self.temp.workspaces,
        )

    def test_dispatch_creates_identity_trace_artifact_and_attestation(self):
        dispatcher = self.dispatcher("worker")
        result = dispatcher.dispatch(ExecutionRequest(agent_id="worker", task="deliver"))
        self.assertEqual("succeeded", result.status)
        self.assertTrue(result.execution_id.startswith("exe-"))
        self.assertEqual("worker", result.attestation["agent_id"])
        self.assertEqual(1, len(result.artifacts))
        row = self.temp.db.one(
            "SELECT * FROM executions WHERE execution_id=?", (result.execution_id,)
        )
        self.assertEqual("succeeded", row["status"])
        self.assertEqual(result.attestation["output_hash"], row["output_hash"])
        events = self.temp.db.all(
            "SELECT event_type FROM execution_events WHERE execution_id=?",
            (result.execution_id,),
        )
        self.assertEqual(
            ["execution.queued", "execution.started", "execution.completed"],
            [event["event_type"] for event in events],
        )

    def test_runtime_identity_attests_agent_message(self):
        dispatcher = self.dispatcher("sender", backend="messaging")
        bus = MessageBus(self.temp.db)
        dispatcher.register_executor(MessagingExecutor(bus))
        result = dispatcher.dispatch(ExecutionRequest(agent_id="sender", task="review this"))
        message = self.temp.db.one(
            "SELECT * FROM messages WHERE message_id=?",
            (result.structured_output["message_id"],),
        )
        self.assertEqual(result.execution_id, message["sender_execution_id"])
        self.assertEqual("sender", message["sender_agent_id"])
        self.assertEqual(1, message["attested"])

    def test_paid_calls_are_allowed_by_default(self):
        self.assertTrue(ExecutionConstraints().allow_paid_calls)

    def test_paid_executor_is_denied_when_explicitly_disabled_and_audited(self):
        dispatcher = self.dispatcher("paid", backend="claude")
        result = dispatcher.dispatch(ExecutionRequest(
            agent_id="paid",
            task="do not call",
            constraints=ExecutionConstraints(allow_paid_calls=False),
        ))
        self.assertEqual("failed", result.status)
        self.assertEqual("PermissionError", result.error["type"])
        row = self.temp.db.one(
            "SELECT status, error_json FROM executions WHERE execution_id=?",
            (result.execution_id,),
        )
        self.assertEqual("failed", row["status"])

    def test_verifier_identity_is_independent_and_persisted(self):
        dispatcher = self.dispatcher("producer")
        self.temp.add_agent("verifier")
        dispatcher.registry.build()
        produced = dispatcher.dispatch(
            ExecutionRequest(agent_id="producer", task="produce")
        )
        with self.assertRaises(PermissionError):
            dispatcher.verify(
                verifier_agent_id="producer",
                subject_execution_id=produced.execution_id,
                task="self review",
            )
        verdict = dispatcher.verify(
            verifier_agent_id="verifier",
            subject_execution_id=produced.execution_id,
            task="independent review",
        )
        self.assertEqual("verifier", verdict.verifier_identity["agent_id"])
        self.assertEqual(
            produced.execution_id,
            verdict.verifier_identity["subject_execution_id"],
        )
        row = self.temp.db.one(
            "SELECT verifier_identity_json FROM executions WHERE execution_id=?",
            (verdict.execution_id,),
        )
        self.assertIn("subject_execution_id", row["verifier_identity_json"])


if __name__ == "__main__":
    unittest.main()
