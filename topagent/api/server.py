from __future__ import annotations

import json
import mimetypes
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from topagent import __version__
from topagent.bus.store import MessageBus
from topagent.core.database import Database, db, load_json
from topagent.core.models import ExecutionConstraints, ExecutionRequest
from topagent.memory.store import MemoryStore
from topagent.registry.builder import build_all
from topagent.runtime.dispatcher import Dispatcher
from topagent.runtime.orchestrator import RuntimeOrchestrator


DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


def _decode_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        for key in list(row):
            if key.endswith("_json"):
                row[key[:-5]] = load_json(row.pop(key), None)
    return rows


class ControlCenter:
    def __init__(self, database: Database | None = None):
        self.db = database or db
        self.db.initialize()
        self.registry_summary = build_all(self.db)
        self.bus = MessageBus(self.db)
        self.memory = MemoryStore(self.db)
        self.dispatcher = Dispatcher(database=self.db)
        self.orchestrator = RuntimeOrchestrator(
            database=self.db, dispatcher=self.dispatcher
        )

    def health(self) -> dict[str, Any]:
        dead = self.db.one(
            "SELECT COUNT(*) AS count FROM messages WHERE status='dead_letter'"
        )["count"]
        running = self.db.one(
            "SELECT COUNT(*) AS count FROM executions WHERE status='running'"
        )["count"]
        return {
            "ok": True,
            "version": __version__,
            "database": str(self.db.path),
            "registry": self.registry_summary,
            "signals": {"dead_letters": dead, "running_executions": running},
        }

    def metrics(self) -> dict[str, Any]:
        execution_rows = self.db.all(
            "SELECT status, COUNT(*) AS count FROM executions GROUP BY status"
        )
        return {
            "executions": {row["status"]: row["count"] for row in execution_rows},
            "messages": self.bus.stats(),
            "memory": {
                row["status"]: row["count"]
                for row in self.db.all(
                    "SELECT status, COUNT(*) AS count FROM memories GROUP BY status"
                )
            },
            "agents": self.db.one("SELECT COUNT(*) AS count FROM agents")["count"],
            "skills": self.db.one("SELECT COUNT(*) AS count FROM skills")["count"],
            "capabilities": self.db.one("SELECT COUNT(*) AS count FROM capabilities")["count"],
        }

    def get_collection(self, name: str, query: dict[str, list[str]]) -> Any:
        limit = min(int(query.get("limit", [100])[0]), 500)
        if name == "health":
            return self.health()
        if name == "metrics":
            return self.metrics()
        if name == "runs":
            return _decode_rows(self.db.all(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ))
        if name == "executions":
            return _decode_rows(self.db.all(
                "SELECT * FROM executions ORDER BY created_at DESC LIMIT ?", (limit,)
            ))
        if name == "events":
            return _decode_rows(self.db.all(
                "SELECT * FROM execution_events ORDER BY occurred_at DESC LIMIT ?", (limit,)
            ))
        if name == "messages":
            return self.bus.list(
                recipient_agent_id=query.get("recipient", [None])[0],
                status=query.get("status", [None])[0], limit=limit,
            )
        if name == "memory":
            return self.memory.list(status=query.get("status", [None])[0], limit=limit)
        if name == "agents":
            return _decode_rows(self.db.all("SELECT * FROM agents ORDER BY agent_id"))
        if name == "skills":
            return _decode_rows(self.db.all("SELECT * FROM skills ORDER BY skill_id"))
        if name == "capabilities":
            return _decode_rows(self.db.all(
                """SELECT c.*,
                   (SELECT COUNT(*) FROM capability_evidence e
                    WHERE e.capability_id=c.capability_id) AS evidence_count,
                   (SELECT MAX(recorded_at) FROM capability_evidence e
                    WHERE e.capability_id=c.capability_id) AS latest_evidence_at
                FROM capabilities c ORDER BY capability_id"""
            ))
        if name == "audit":
            return _decode_rows(self.db.all(
                "SELECT * FROM audit_records ORDER BY occurred_at DESC LIMIT ?", (limit,)
            ))
        if name == "presence":
            return _decode_rows(self.db.all(
                "SELECT * FROM agent_presence ORDER BY last_heartbeat_at DESC"
            ))
        raise KeyError(name)

    def get_item(self, collection: str, item_id: str) -> Any:
        table_key = {
            "runs": ("runs", "run_id"),
            "executions": ("executions", "execution_id"),
            "messages": ("messages", "message_id"),
            "memory": ("memories", "memory_id"),
        }.get(collection)
        if not table_key:
            raise KeyError(collection)
        table, key = table_key
        row = self.db.one(f"SELECT * FROM {table} WHERE {key}=?", (item_id,))
        if not row:
            raise KeyError(item_id)
        return _decode_rows([row])[0]

    def post(self, path: list[str], body: dict[str, Any]) -> Any:
        if path == ["runs"]:
            run_id = self.orchestrator.create_run(
                str(body["requirement"]), metadata=body.get("metadata")
            )
            return {"ok": True, "run_id": run_id}
        if len(path) == 4 and path[0] == "runs" and path[2] == "steps":
            result = self.orchestrator.run_step(
                path[1], path[3],
                allow_paid_calls=bool(body.get("allow_paid_calls", True)),
                timeout_seconds=int(body.get("timeout_seconds", 300)),
                shared_inputs=body.get("inputs"),
            )
            return result.__dict__
        if path == ["dispatch"]:
            constraints = ExecutionConstraints(
                timeout_seconds=int(body.get("timeout_seconds", 300)),
                max_turns=int(body.get("max_turns", 10)),
                allow_paid_calls=bool(body.get("allow_paid_calls", True)),
                metadata=body.get("metadata") or {},
            )
            result = self.dispatcher.dispatch(
                ExecutionRequest(
                    agent_id=str(body["agent_id"]), task=str(body["task"]),
                    run_id=body.get("run_id"), constraints=constraints,
                )
            )
            return result.to_dict()
        if path == ["verify"]:
            constraints = ExecutionConstraints(
                timeout_seconds=int(body.get("timeout_seconds", 300)),
                max_turns=int(body.get("max_turns", 10)),
                allow_paid_calls=bool(body.get("allow_paid_calls", True)),
                metadata=body.get("metadata") or {},
            )
            return self.dispatcher.verify(
                verifier_agent_id=str(body["verifier_agent_id"]),
                subject_execution_id=str(body["subject_execution_id"]),
                task=str(body["task"]),
                constraints=constraints,
            ).to_dict()
        if path == ["memory", "candidates"]:
            return self.memory.add_candidate(**body).__dict__
        if len(path) == 3 and path[0] == "memory" and path[2] == "promote":
            return self.memory.promote(
                path[1], verified_by=str(body["verified_by"]),
                supersede_existing=bool(body.get("supersede_existing", False)),
            ).__dict__
        if len(path) == 3 and path[0] == "memory" and path[2] == "archive":
            return self.memory.archive(
                path[1], actor=str(body["actor"]), reason=str(body["reason"])
            ).__dict__
        if path == ["messages", "requeue-expired"]:
            return {"ok": True, "requeued": self.bus.requeue_expired()}
        raise KeyError("/".join(path))


class ControlCenterHandler(BaseHTTPRequestHandler):
    server_version = "TopAgentControlCenter/3.0"
    center: ControlCenter

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            if parsed.path == "/api/events/stream":
                self._sse(parse_qs(parsed.query))
                return
            if parts and parts[0] == "api":
                if len(parts) == 2:
                    payload = self.center.get_collection(parts[1], parse_qs(parsed.query))
                elif len(parts) == 3:
                    payload = self.center.get_item(parts[1], parts[2])
                else:
                    raise KeyError(parsed.path)
                self._json(payload)
                return
            self._static(parsed.path)
        except KeyError as exc:
            self._json({"ok": False, "error": f"not found: {exc}"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            if not parts or parts[0] != "api":
                raise KeyError(parsed.path)
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            self._json(self.center.post(parts[1:], body), HTTPStatus.CREATED)
        except KeyError as exc:
            self._json({"ok": False, "error": f"not found: {exc}"}, HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (DASHBOARD_DIR / relative).resolve()
        if DASHBOARD_DIR.resolve() not in target.parents and target != DASHBOARD_DIR.resolve():
            raise KeyError(request_path)
        if not target.is_file():
            raise KeyError(request_path)
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, query: dict[str, list[str]]) -> None:
        after = query.get("after", [""])[0]
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if after:
                rows = self.center.db.all(
                    """SELECT * FROM execution_events WHERE occurred_at>?
                    ORDER BY occurred_at, event_id LIMIT 100""", (after,)
                )
            else:
                rows = []
            if rows:
                for row in _decode_rows(rows):
                    after = row["occurred_at"]
                    packet = json.dumps(row, ensure_ascii=False).replace("\n", "\\n")
                    self.wfile.write(f"id: {after}\nevent: trace\ndata: {packet}\n\n".encode("utf-8"))
                self.wfile.flush()
            else:
                self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
            time.sleep(1)

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server(
    host: str = "127.0.0.1", port: int = 8765, *, database: Database | None = None
) -> ThreadingHTTPServer:
    center = ControlCenter(database)

    class BoundHandler(ControlCenterHandler):
        pass

    BoundHandler.center = center
    return ThreadingHTTPServer((host, port), BoundHandler)


def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = create_server(host, port)
    print(f"TopAgent Control Center: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
