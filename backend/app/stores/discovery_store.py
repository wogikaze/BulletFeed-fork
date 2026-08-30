from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.database import Database
from app.db.discovery_schema import DISCOVERY_SCHEMA


@dataclass(frozen=True)
class DiscoveryCandidate:
    id: str
    discovery_method: str
    discovery_url: str
    target_url: str
    publisher_timestamp: str | None
    metadata: dict[str, Any]
    first_seen_at: str
    last_seen_at: str


class DiscoveryStore:
    """Store fetch candidates without promoting discovery signals to Observations/Claims."""

    def __init__(self, database: Database) -> None:
        self._database = database
        with self._database.connect() as connection:
            connection.executescript(DISCOVERY_SCHEMA)

    def upsert(
        self,
        *,
        discovery_method: str,
        discovery_url: str,
        target_url: str,
        publisher_timestamp: str | None,
        metadata: dict[str, Any],
        seen_at: str,
    ) -> DiscoveryCandidate:
        candidate_id = "cand_" + hashlib.sha256(
            f"{discovery_method}|{discovery_url}|{target_url}".encode()
        ).hexdigest()[:24]
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO discovery_candidates (
                    id, discovery_method, discovery_url, target_url, publisher_timestamp,
                    metadata_json, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(discovery_method, discovery_url, target_url) DO UPDATE SET
                    publisher_timestamp = excluded.publisher_timestamp,
                    metadata_json = excluded.metadata_json,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    candidate_id,
                    discovery_method,
                    discovery_url,
                    target_url,
                    publisher_timestamp,
                    metadata_json,
                    seen_at,
                    seen_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM discovery_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("discovery candidate upsert failed")
        return self._row(row)

    def list_all(self, *, limit: int = 500) -> list[DiscoveryCandidate]:
        capped = max(1, min(int(limit), 2000))
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM discovery_candidates
                ORDER BY last_seen_at DESC, target_url
                LIMIT ?
                """,
                (capped,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_for_discovery_url(self, discovery_url: str) -> list[DiscoveryCandidate]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM discovery_candidates
                WHERE discovery_url = ?
                ORDER BY target_url
                """,
                (discovery_url,),
            ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row) -> DiscoveryCandidate:
        return DiscoveryCandidate(
            id=row["id"],
            discovery_method=row["discovery_method"],
            discovery_url=row["discovery_url"],
            target_url=row["target_url"],
            publisher_timestamp=row["publisher_timestamp"],
            metadata=json.loads(row["metadata_json"]),
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
        )
