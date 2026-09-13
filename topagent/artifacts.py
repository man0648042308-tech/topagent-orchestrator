from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from topagent.core.database import Database, db, dump_json
from topagent.core.ids import new_id
from topagent.core.models import ArtifactRef, utc_now
from topagent.settings import settings


class ArtifactStore:
    def __init__(self, database: Database | None = None, root: Path | None = None):
        self.db = database or db
        self.root = root or settings.artifact_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        data: bytes,
        *,
        media_type: str = "application/octet-stream",
        suffix: str = "",
        execution_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        digest = hashlib.sha256(data).hexdigest()
        existing = self.db.one(
            "SELECT * FROM artifacts WHERE sha256=? AND media_type=?",
            (digest, media_type),
        )
        if existing:
            return ArtifactRef(
                existing["artifact_id"], existing["sha256"], existing["media_type"],
                existing["path"], existing["size_bytes"]
            )
        artifact_id = new_id("art")
        target_dir = self.root / digest[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{digest}{suffix}"
        target.write_bytes(data)
        self.db.execute(
            """INSERT INTO artifacts
            (artifact_id, execution_id, sha256, media_type, path, size_bytes, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id, execution_id, digest, media_type, str(target), len(data),
                utc_now(), dump_json(metadata or {}),
            ),
        )
        return ArtifactRef(artifact_id, digest, media_type, str(target), len(data))

    def put_text(
        self,
        text: str,
        *,
        media_type: str = "text/plain",
        execution_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        suffix = ".json" if media_type == "application/json" else ".txt"
        return self.put_bytes(
            text.encode("utf-8"), media_type=media_type, suffix=suffix,
            execution_id=execution_id, metadata=metadata,
        )

    def put_json(
        self,
        value: Any,
        *,
        execution_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        return self.put_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            media_type="application/json", execution_id=execution_id, metadata=metadata,
        )

    def import_file(
        self,
        source: str | Path,
        *,
        media_type: str = "application/octet-stream",
        execution_id: str | None = None,
    ) -> ArtifactRef:
        path = Path(source)
        return self.put_bytes(
            path.read_bytes(), media_type=media_type, suffix=path.suffix,
            execution_id=execution_id, metadata={"source_path": str(path)},
        )

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,))


artifacts = ArtifactStore()
