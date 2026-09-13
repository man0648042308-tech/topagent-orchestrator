from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable

from topagent.bus.service import BusService
from topagent.bus.store import MessageBus
from topagent.core.context import ExecutionIdentity, execution_identity
from topagent.core.database import Database, db, dump_json
from topagent.core.ids import new_id
from topagent.core.models import utc_now
from topagent.registry.builder import build_all


def _object_schema(
    properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: dict[str, dict[str, Any]] = {
    "send_message": {
        "description": "发送持久消息。提供 sender_execution_id 时由 Runtime 验证身份；旧 from 字段仅标记为未认证。",
        "inputSchema": _object_schema(
            {
                "recipient_agent_id": {"type": "string"},
                "to": {"type": "string", "description": "兼容旧字段"},
                "sender_execution_id": {"type": "string"},
                "from": {"type": "string", "description": "兼容旧字段，未认证"},
                "message_type": {"type": "string"},
                "type": {"type": "string", "description": "兼容旧字段"},
                "payload": {"type": "object"},
                "body": {"type": "object", "description": "兼容旧字段"},
                "thread_id": {"type": "string"},
                "correlation_id": {"type": "string"},
                "causation_id": {"type": "string"},
                "priority": {"type": ["integer", "string"]},
                "idempotency_key": {"type": "string"},
                "max_attempts": {"type": "integer", "minimum": 1, "maximum": 20},
                "expires_at": {"type": "string"},
            }
        ),
    },
    "lease_messages": {
        "description": "为 worker 租约消息；处理完必须调用 acknowledge_message 或 fail_message。",
        "inputSchema": _object_schema(
            {
                "recipient_agent_id": {"type": "string"},
                "worker_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "lease_seconds": {"type": "integer", "minimum": 5, "maximum": 3600},
            },
            ["recipient_agent_id", "worker_id"],
        ),
    },
    "read_messages": {
        "description": "旧接口兼容：读取操作现在返回租约及 delivery_id，不再以读代完成。",
        "inputSchema": _object_schema(
            {
                "agent": {"type": "string"},
                "worker_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "lease_seconds": {"type": "integer", "minimum": 5, "maximum": 3600},
                "mark_read": {"type": "boolean", "description": "保留字段，不再自动完成"},
            },
            ["agent"],
        ),
    },
    "acknowledge_message": {
        "description": "确认消息已处理；delivery_id 防止把别人的租约误确认。",
        "inputSchema": _object_schema(
            {
                "message_id": {"type": "string"},
                "delivery_id": {"type": "string"},
                "completed": {"type": "boolean"},
            },
            ["message_id", "delivery_id"],
        ),
    },
    "fail_message": {
        "description": "报告处理失败；按 max_attempts 自动进入延时重试或死信。",
        "inputSchema": _object_schema(
            {
                "message_id": {"type": "string"},
                "delivery_id": {"type": "string"},
                "error": {"type": "string"},
                "retry_delay": {"type": "integer", "minimum": 0, "maximum": 86400},
            },
            ["message_id", "delivery_id", "error"],
        ),
    },
    "list_messages": {
        "description": "按接收方或状态查询持久消息，用于审计和恢复。",
        "inputSchema": _object_schema(
            {
                "recipient_agent_id": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            }
        ),
    },
    "requeue_expired": {
        "description": "回收过期租约并重新入队。",
        "inputSchema": _object_schema({}),
    },
    "heartbeat": {
        "description": "写入 Agent/worker 活性与当前执行状态。",
        "inputSchema": _object_schema(
            {
                "agent": {"type": "string"},
                "worker_id": {"type": "string"},
                "state": {"type": "string"},
                "current_execution_id": {"type": "string"},
                "metadata": {"type": "object"},
            },
            ["agent"],
        ),
    },
    "register_agent": {
        "description": "旧接口兼容：刷新 presence；Agent 定义仍以 .claude/agents 文件为唯一事实源。",
        "inputSchema": _object_schema(
            {
                "name": {"type": "string"},
                "worker_id": {"type": "string"},
                "role": {"type": "string"},
                "capabilities": {"type": "array", "items": {"type": "string"}},
            },
            ["name"],
        ),
    },
    "list_agents": {
        "description": "列出版本化 Agent 定义及在线 worker。",
        "inputSchema": _object_schema({}),
    },
    "list_tools": {
        "description": "列出本 Bridge 的可调用工具与准确 Schema。",
        "inputSchema": _object_schema({}),
    },
    "register_tool": {
        "description": "旧接口兼容：记录工具声明到审计日志，不改变服务器代码。",
        "inputSchema": _object_schema(
            {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "level": {"type": "integer"},
                "owner": {"type": "string"},
            },
            ["name"],
        ),
    },
    "get_message_stats": {
        "description": "获取 queued/leased/processing/retry/dead-letter 等状态指标。",
        "inputSchema": _object_schema({}),
    },
}


class MCPBridge:
    def __init__(self, database: Database | None = None):
        self.db = database or db
        self.db.initialize()
        build_all(self.db)
        self.bus = MessageBus(self.db)
        self.service = BusService(self.bus)

    def call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "send_message": self.send_message,
            "lease_messages": self.service.lease,
            "read_messages": self.read_messages,
            "acknowledge_message": self.acknowledge,
            "fail_message": self.fail,
            "list_messages": self.list_messages,
            "requeue_expired": lambda _: {"ok": True, "requeued": self.bus.requeue_expired()},
            "heartbeat": self.heartbeat,
            "register_agent": self.register_agent,
            "list_agents": self.list_agents,
            "list_tools": lambda _: {"ok": True, "tools": self.tool_list()},
            "register_tool": self.register_tool,
            "get_message_stats": lambda _: {"ok": True, **self.bus.stats()},
        }
        if name not in handlers:
            raise KeyError(f"Unknown tool: {name}")
        return handlers[name](params)

    @staticmethod
    def tool_list() -> list[dict[str, Any]]:
        return [
            {"name": name, **definition}
            for name, definition in sorted(TOOLS.items())
        ]

    def send_message(self, params: dict[str, Any]) -> dict[str, Any]:
        execution_id = params.get("sender_execution_id")
        if execution_id:
            row = self.db.one("SELECT * FROM executions WHERE execution_id=?", (execution_id,))
            if not row:
                raise PermissionError("sender_execution_id 不存在")
            identity = ExecutionIdentity(
                execution_id=row["execution_id"], agent_id=row["agent_id"],
                agent_version=row["agent_version"], backend=row["backend"], model=row["model"],
            )
            with execution_identity(identity):
                result = self.service.send(params)
            result["attested"] = True
            return result
        result = self.service.send(params, legacy=True)
        result["attested"] = False
        result["warning"] = "legacy sender identity is not runtime-attested"
        return result

    def read_messages(self, params: dict[str, Any]) -> dict[str, Any]:
        translated = dict(params)
        translated["recipient_agent_id"] = translated.pop("agent")
        translated.setdefault("worker_id", f"legacy-mcp-{translated['recipient_agent_id']}")
        result = self.service.lease(translated)
        result["compatibility_note"] = "messages are leased; acknowledge_message is required"
        return result

    def acknowledge(self, params: dict[str, Any]) -> dict[str, Any]:
        self.bus.acknowledge(
            params["message_id"], params["delivery_id"],
            completed=bool(params.get("completed", True)),
        )
        return {"ok": True, "message_id": params["message_id"]}

    def fail(self, params: dict[str, Any]) -> dict[str, Any]:
        status = self.bus.fail(
            params["message_id"], params["delivery_id"], params["error"],
            retry_delay=int(params.get("retry_delay", 5)),
        )
        return {"ok": True, "message_id": params["message_id"], "status": status}

    def list_messages(self, params: dict[str, Any]) -> dict[str, Any]:
        rows = self.bus.list(
            recipient_agent_id=params.get("recipient_agent_id"),
            status=params.get("status"), limit=int(params.get("limit", 100)),
        )
        return {"ok": True, "count": len(rows), "messages": rows}

    def heartbeat(self, params: dict[str, Any]) -> dict[str, Any]:
        agent = params["agent"]
        worker = params.get("worker_id") or f"mcp-{agent}"
        self._presence(
            agent, worker, params.get("state", "online"),
            params.get("current_execution_id"), params.get("metadata") or {},
        )
        return {"ok": True, "agent": agent, "worker_id": worker}

    def register_agent(self, params: dict[str, Any]) -> dict[str, Any]:
        worker = params.get("worker_id") or f"legacy-{params['name']}"
        self._presence(
            params["name"], worker, "online", None,
            {"role": params.get("role"), "capabilities": params.get("capabilities", [])},
        )
        return {"ok": True, "agent": params["name"], "worker_id": worker}

    def list_agents(self, _: dict[str, Any]) -> dict[str, Any]:
        agents = self.db.all("SELECT * FROM agents ORDER BY agent_id")
        presence = self.db.all("SELECT * FROM agent_presence ORDER BY agent_id, worker_id")
        return {"ok": True, "agents": agents, "presence": presence}

    def register_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        self.db.execute(
            """INSERT INTO audit_records
            (audit_id, actor_type, actor_id, action, target_type, target_id,
             occurred_at, detail_json) VALUES (?, 'legacy-mcp', ?, 'tool.declared',
             'tool', ?, ?, ?)""",
            (
                new_id("aud"), params.get("owner", "unknown"), params["name"],
                utc_now(), dump_json(params),
            ),
        )
        return {"ok": True, "tool": params["name"], "registered": "audit-only"}

    def _presence(
        self, agent: str, worker: str, state: str, execution_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.db.execute(
            """INSERT INTO agent_presence
            (agent_id, worker_id, state, current_execution_id, last_heartbeat_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, worker_id) DO UPDATE SET
              state=excluded.state,
              current_execution_id=excluded.current_execution_id,
              last_heartbeat_at=excluded.last_heartbeat_at,
              metadata_json=excluded.metadata_json""",
            (agent, worker, state, execution_id, utc_now(), dump_json(metadata)),
        )


def response(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def handle_request(bridge: MCPBridge, request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    req_id = request.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return response(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "topagent-mcp-bridge", "version": "3.0.0"},
                "capabilities": {"tools": {"listChanged": False}},
            },
        )
    if method == "ping":
        return response(req_id, {})
    if method == "tools/list":
        return response(req_id, {"tools": bridge.tool_list()})
    if method == "tools/call":
        params = request.get("params") or {}
        result = bridge.call(params.get("name", ""), params.get("arguments") or {})
        return response(
            req_id,
            {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
        )
    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main() -> None:
    bridge = MCPBridge()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            answer = handle_request(bridge, request)
            if answer is not None:
                sys.stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            req_id = request.get("id") if "request" in locals() else None
            error = {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": f"{type(exc).__name__}: {exc}"},
            }
            sys.stdout.write(json.dumps(error, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
