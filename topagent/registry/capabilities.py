from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from topagent.core.database import Database, db, dump_json
from topagent.core.ids import new_id
from topagent.core.models import utc_now
from topagent.settings import settings


class CapabilityRegistry:
    def __init__(self, database: Database | None = None, root: Path | None = None):
        self.db = database or db
        self.root = root or settings.capabilities_dir

    def build(self) -> list[dict[str, Any]]:
        results = []
        if not self.root.exists():
            return results
        seen: set[str] = set()
        for path in sorted(self.root.glob("*.json")):
            contract = json.loads(path.read_text(encoding="utf-8"))
            capability_id = contract["capability_id"]
            if capability_id in seen:
                raise ValueError(f"重复 Capability ID: {capability_id}")
            seen.add(capability_id)
            raw = dump_json(contract)
            self.db.execute(
                """INSERT INTO capabilities
                (capability_id, name, status, maturity, owner, contract_json,
                 content_hash, updated_at, last_verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                  name=excluded.name, status=excluded.status, maturity=excluded.maturity,
                  owner=excluded.owner, contract_json=excluded.contract_json,
                  content_hash=excluded.content_hash, updated_at=excluded.updated_at,
                  last_verified_at=excluded.last_verified_at""",
                (
                    capability_id, contract.get("name", capability_id),
                    contract.get("status", "declared"), contract.get("maturity", "L0-declared"),
                    contract.get("owner"), raw, hashlib.sha256(raw.encode()).hexdigest(),
                    utc_now(), contract.get("verification", {}).get("last_verified_at"),
                ),
            )
            results.append(contract)
        for row in self.db.all("SELECT capability_id FROM capabilities"):
            if row["capability_id"] not in seen:
                self.db.execute(
                    "DELETE FROM capabilities WHERE capability_id=?",
                    (row["capability_id"],),
                )
        return results

    def evidence(
        self, capability_id: str, evidence_type: str, reference: str,
        *, execution_id: str | None = None, status: str = "passed",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        evidence_id = new_id("evidence")
        self.db.execute(
            """INSERT INTO capability_evidence
            (evidence_id, capability_id, evidence_type, reference, execution_id,
             status, recorded_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evidence_id, capability_id, evidence_type, reference, execution_id,
                status, utc_now(), dump_json(metadata or {}),
            ),
        )
        return evidence_id

    def list(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM capabilities ORDER BY capability_id")


capability_registry = CapabilityRegistry()
