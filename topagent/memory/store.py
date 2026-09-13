from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from topagent.core.database import Database, db, dump_json, load_json
from topagent.core.ids import new_id
from topagent.core.models import utc_now
from topagent.settings import settings


@dataclass
class MemoryRecord:
    memory_id: str
    namespace: str
    memory_type: str
    subject: str
    content: str
    confidence: float
    status: str
    tags: list[str]
    source_execution_id: str | None = None
    source_artifact_id: str | None = None
    supersedes: str | None = None
    conflicts: list[str] | None = None


class MemoryStore:
    """候选→验证→晋升/冲突→归档的记忆生命周期。"""

    def __init__(
        self,
        database: Database | None = None,
        *,
        candidate_dir: Path | None = None,
        canonical_dir: Path | None = None,
        archive_dir: Path | None = None,
    ):
        self.db = database or db
        self.db.initialize()
        self.candidate_dir = candidate_dir or settings.candidate_memory_dir
        self.canonical_dir = canonical_dir or settings.canonical_memory_dir
        self.archive_dir = archive_dir or settings.archive_memory_dir
        for path in (self.candidate_dir, self.canonical_dir, self.archive_dir):
            path.mkdir(parents=True, exist_ok=True)

    def add_candidate(
        self,
        *,
        namespace: str,
        memory_type: str,
        subject: str,
        content: str,
        confidence: float = 0.5,
        tags: list[str] | None = None,
        visibility: list[str] | None = None,
        source_execution_id: str | None = None,
        source_artifact_id: str | None = None,
    ) -> MemoryRecord:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence 必须在 0..1")
        memory_id = new_id("mem")
        now = utc_now()
        record = MemoryRecord(
            memory_id=memory_id,
            namespace=namespace,
            memory_type=memory_type,
            subject=subject,
            content=content,
            confidence=confidence,
            status="candidate",
            tags=tags or [],
            source_execution_id=source_execution_id,
            source_artifact_id=source_artifact_id,
            conflicts=[],
        )
        self.db.execute(
            """INSERT INTO memories
            (memory_id, namespace, memory_type, subject, content,
             source_execution_id, source_artifact_id, confidence, status,
             visibility_json, tags_json, conflicts_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, '[]', ?, ?)""",
            (
                memory_id, namespace, memory_type, subject, content,
                source_execution_id, source_artifact_id, confidence,
                dump_json(visibility or []), dump_json(tags or []), now, now,
            ),
        )
        self._index(record)
        self._write_record(self.candidate_dir, record)
        self._audit("memory.candidate.created", memory_id, {"namespace": namespace})
        return record

    def promote(
        self,
        memory_id: str,
        *,
        verified_by: str,
        supersede_existing: bool = False,
    ) -> MemoryRecord:
        row = self._require(memory_id)
        if row["status"] not in {"candidate", "conflict"}:
            raise ValueError(f"只有 candidate/conflict 可晋升，当前为 {row['status']}")
        active = self.db.all(
            """SELECT memory_id, content FROM memories
            WHERE namespace=? AND subject=? AND status='active' AND memory_id<>?""",
            (row["namespace"], row["subject"], memory_id),
        )
        conflicts = [item["memory_id"] for item in active if item["content"] != row["content"]]
        if conflicts and not supersede_existing:
            self.db.execute(
                "UPDATE memories SET status='conflict', conflicts_json=?, updated_at=? WHERE memory_id=?",
                (dump_json(conflicts), utc_now(), memory_id),
            )
            self._audit(
                "memory.conflict.detected", memory_id,
                {"conflicts": conflicts, "verified_by": verified_by},
            )
            return self.get(memory_id)
        now = utc_now()
        supersedes = None
        if conflicts:
            supersedes = conflicts[0]
            for old_id in conflicts:
                self.db.execute(
                    "UPDATE memories SET status='superseded', updated_at=? WHERE memory_id=?",
                    (now, old_id),
                )
                old = self.get(old_id)
                self._write_record(self.archive_dir, old)
        self.db.execute(
            """UPDATE memories SET status='active', supersedes=?, conflicts_json='[]',
               last_verified_at=?, updated_at=? WHERE memory_id=?""",
            (supersedes, now, now, memory_id),
        )
        promoted = self.get(memory_id)
        self._write_record(self.canonical_dir, promoted)
        candidate_file = self._path_for(self.candidate_dir, promoted)
        if candidate_file.exists():
            candidate_file.unlink()
        self._audit(
            "memory.promoted", memory_id,
            {"verified_by": verified_by, "supersedes": supersedes},
        )
        return promoted

    def archive(self, memory_id: str, *, actor: str, reason: str) -> MemoryRecord:
        record = self.get(memory_id)
        self.db.execute(
            "UPDATE memories SET status='archived', updated_at=? WHERE memory_id=?",
            (utc_now(), memory_id),
        )
        archived = self.get(memory_id)
        self._write_record(self.archive_dir, archived)
        canonical = self._path_for(self.canonical_dir, record)
        if canonical.exists():
            canonical.unlink()
        self._audit("memory.archived", memory_id, {"actor": actor, "reason": reason})
        return archived

    def search(
        self,
        query: str,
        *,
        namespace: str | None = None,
        include_candidates: bool = False,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        statuses = ("active", "candidate", "conflict") if include_candidates else ("active",)
        placeholders = ",".join("?" for _ in statuses)
        clauses = [f"m.status IN ({placeholders})", "memory_fts MATCH ?"]
        params: list[Any] = list(statuses) + [self._fts_query(query)]
        if namespace:
            clauses.append("m.namespace=?")
            params.append(namespace)
        params.append(limit)
        rows = self.db.all(
            f"""SELECT m.* FROM memory_fts
            JOIN memories m ON m.memory_id=memory_fts.memory_id
            WHERE {' AND '.join(clauses)}
            ORDER BY bm25(memory_fts), m.confidence DESC LIMIT ?""",
            params,
        )
        records = [self._from_row(row) for row in rows]
        now = utc_now()
        for record in records:
            self.db.execute(
                "UPDATE memories SET use_count=use_count+1, last_used_at=? WHERE memory_id=?",
                (now, record.memory_id),
            )
        return records

    def get(self, memory_id: str) -> MemoryRecord:
        return self._from_row(self._require(memory_id))

    def list(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            rows = self.db.all(
                "SELECT * FROM memories WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = self.db.all(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        for row in rows:
            row["tags"] = load_json(row.pop("tags_json"), [])
            row["visibility"] = load_json(row.pop("visibility_json"), [])
            row["conflicts"] = load_json(row.pop("conflicts_json"), [])
        return rows

    def _require(self, memory_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM memories WHERE memory_id=?", (memory_id,))
        if not row:
            raise KeyError(memory_id)
        return row

    def _index(self, record: MemoryRecord) -> None:
        self.db.execute("DELETE FROM memory_fts WHERE memory_id=?", (record.memory_id,))
        self.db.execute(
            "INSERT INTO memory_fts(memory_id, subject, content, tags) VALUES (?, ?, ?, ?)",
            (record.memory_id, record.subject, record.content, " ".join(record.tags)),
        )

    @staticmethod
    def _from_row(row: dict[str, Any]) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"], namespace=row["namespace"],
            memory_type=row["memory_type"], subject=row["subject"],
            content=row["content"], confidence=row["confidence"], status=row["status"],
            tags=load_json(row.get("tags_json"), []),
            source_execution_id=row.get("source_execution_id"),
            source_artifact_id=row.get("source_artifact_id"),
            supersedes=row.get("supersedes"),
            conflicts=load_json(row.get("conflicts_json"), []),
        )

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[\w\-]+", query, flags=re.UNICODE)
        return " OR ".join(f'"{token}"' for token in tokens) or '""'

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^\w\-.]+", "-", value, flags=re.UNICODE).strip("-")
        return slug[:60] or "memory"

    def _path_for(self, directory: Path, record: MemoryRecord) -> Path:
        return directory / f"{self._slug(record.subject)}--{record.memory_id}.md"

    def _write_record(self, directory: Path, record: MemoryRecord) -> Path:
        path = self._path_for(directory, record)
        header = (
            "---\n"
            f"memory_id: {record.memory_id}\n"
            f"namespace: {record.namespace}\n"
            f"type: {record.memory_type}\n"
            f"status: {record.status}\n"
            f"confidence: {record.confidence}\n"
            f"tags: {dump_json(record.tags)}\n"
            f"source_execution_id: {record.source_execution_id or ''}\n"
            f"supersedes: {record.supersedes or ''}\n"
            "---\n\n"
        )
        path.write_text(f"{header}# {record.subject}\n\n{record.content}\n", encoding="utf-8")
        return path

    def _audit(self, action: str, memory_id: str, detail: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO audit_records
            (audit_id, actor_type, actor_id, action, target_type, target_id,
             occurred_at, detail_json) VALUES (?, 'runtime', 'memory-store', ?,
             'memory', ?, ?, ?)""",
            (new_id("aud"), action, memory_id, utc_now(), dump_json(detail)),
        )
