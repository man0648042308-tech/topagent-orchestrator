from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from topagent.settings import settings


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    requirement TEXT NOT NULL,
    pipeline_version TEXT,
    status TEXT NOT NULL,
    current_step TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    run_id TEXT,
    parent_execution_id TEXT,
    agent_id TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    backend TEXT NOT NULL,
    model TEXT,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    input_hash TEXT,
    output_hash TEXT,
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT,
    attestation_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_executions_run ON executions(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_executions_agent ON executions(agent_id, created_at);

CREATE TABLE IF NOT EXISTS execution_events (
    event_id TEXT PRIMARY KEY,
    execution_id TEXT,
    run_id TEXT,
    trace_id TEXT,
    parent_event_id TEXT,
    event_type TEXT NOT NULL,
    status TEXT,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_execution ON execution_events(execution_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_trace ON execution_events(trace_id, occurred_at);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    sender_execution_id TEXT,
    sender_agent_id TEXT NOT NULL,
    recipient_agent_id TEXT NOT NULL,
    message_type TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 2,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    visible_at TEXT NOT NULL,
    lease_until TEXT,
    leased_by TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    acknowledged_at TEXT,
    completed_at TEXT,
    last_error TEXT,
    attested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_delivery
ON messages(recipient_agent_id, status, visible_at, priority, created_at);

CREATE TABLE IF NOT EXISTS message_deliveries (
    delivery_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    worker_id TEXT,
    status TEXT NOT NULL,
    leased_at TEXT,
    finished_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    execution_id TEXT,
    sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_sha ON artifacts(sha256, media_type);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT NOT NULL,
    model TEXT,
    backend TEXT NOT NULL,
    prompt_path TEXT NOT NULL,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    skill_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT NOT NULL,
    skill_path TEXT NOT NULL,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    content TEXT NOT NULL,
    source_execution_id TEXT,
    source_artifact_id TEXT,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    visibility_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    supersedes TEXT,
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_verified_at TEXT,
    expires_at TEXT,
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace, status, memory_type);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    memory_id UNINDEXED, subject, content, tags
);

CREATE TABLE IF NOT EXISTS capabilities (
    capability_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    maturity TEXT NOT NULL,
    owner TEXT,
    contract_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_verified_at TEXT
);

CREATE TABLE IF NOT EXISTS capability_evidence (
    evidence_id TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    reference TEXT NOT NULL,
    execution_id TEXT,
    status TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS audit_records (
    audit_id TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    occurred_at TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_presence (
    agent_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    state TEXT NOT NULL,
    current_execution_id TEXT,
    last_heartbeat_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (agent_id, worker_id)
);
"""


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or settings.database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            conn.executescript(SCHEMA)
            self._ensure_column(conn, "executions", "verifier_identity_json", "TEXT")

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection, table: str, column: str, declaration: str
    ) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with closing(self.connect()) as conn:
            cur = conn.execute(sql, tuple(params))
            return cur.rowcount

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


db = Database()
