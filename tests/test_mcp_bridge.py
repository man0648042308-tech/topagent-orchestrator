from __future__ import annotations

import unittest

from topagent.bus.mcp_server import MCPBridge, TOOLS, handle_request
from tests.helpers import TempWorkspace


class MCPBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempWorkspace()
        self.bridge = MCPBridge(self.temp.db)

    def tearDown(self):
        self.temp.close()

    def test_every_tool_has_specific_closed_schema(self):
        self.assertIn("acknowledge_message", TOOLS)
        self.assertIn("fail_message", TOOLS)
        for definition in TOOLS.values():
            schema = definition["inputSchema"]
            self.assertEqual("object", schema["type"])
            self.assertFalse(schema["additionalProperties"])

    def test_legacy_sender_is_unattested_and_ack_flow_is_durable(self):
        sent = self.bridge.call("send_message", {
            "from": "legacy", "to": "worker", "body": {"task": "x"}
        })
        self.assertFalse(sent["attested"])
        leased = self.bridge.call("lease_messages", {
            "recipient_agent_id": "worker", "worker_id": "w1"
        })["messages"][0]
        self.bridge.call("acknowledge_message", {
            "message_id": leased["message_id"], "delivery_id": leased["delivery_id"]
        })
        self.assertEqual("completed", self.bridge.bus.list()[0]["status"])

    def test_protocol_initialize_and_tool_list(self):
        initialized = handle_request(self.bridge, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual("3.0.0", initialized["result"]["serverInfo"]["version"])
        listed = handle_request(self.bridge, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertGreaterEqual(len(listed["result"]["tools"]), 10)


if __name__ == "__main__":
    unittest.main()
