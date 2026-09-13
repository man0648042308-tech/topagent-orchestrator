from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from topagent.bus.models import Message
from topagent.bus.store import MessageBus
from tests.helpers import TempWorkspace


class MessageBusTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempWorkspace()
        self.bus = MessageBus(self.temp.db)

    def tearDown(self):
        self.temp.close()

    def send(self, **overrides):
        values = {
            "recipient_agent_id": "worker",
            "message_type": "task",
            "payload": {"task": "x"},
            "sender_agent_id": "legacy",
        }
        values.update(overrides)
        return self.bus.send(Message(**values), allow_legacy_sender=True)

    def test_lease_requires_matching_delivery_and_acknowledges(self):
        message_id = self.send()
        leased = self.bus.lease("worker", "w1")
        self.assertEqual(1, len(leased))
        with self.assertRaises(PermissionError):
            self.bus.acknowledge(message_id, "wrong")
        self.bus.start_processing(message_id, leased[0].delivery_id)
        self.bus.acknowledge(message_id, leased[0].delivery_id)
        self.assertEqual("completed", self.bus.list()[0]["status"])

    def test_retry_then_dead_letter(self):
        message_id = self.send(max_attempts=2)
        first = self.bus.lease("worker", "w1")[0]
        self.assertEqual("retry_wait", self.bus.fail(
            message_id, first.delivery_id, "first", retry_delay=0
        ))
        second = self.bus.lease("worker", "w1")[0]
        self.assertEqual("dead_letter", self.bus.fail(
            message_id, second.delivery_id, "second", retry_delay=0
        ))

    def test_expired_lease_is_requeued(self):
        message_id = self.send()
        self.bus.lease("worker", "w1", lease_seconds=-1)
        self.assertEqual(1, self.bus.requeue_expired())
        self.assertEqual("queued", self.bus.list()[0]["status"])

    def test_idempotency_key_is_safe_under_concurrency(self):
        def attempt(_):
            return self.send(idempotency_key="same")
        with ThreadPoolExecutor(max_workers=6) as pool:
            ids = list(pool.map(attempt, range(12)))
        self.assertEqual(1, len(set(ids)))
        self.assertEqual(1, self.bus.stats()["total"])


if __name__ == "__main__":
    unittest.main()
