from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.database import Database
from app.db.ledger_schema import LEDGER_SCHEMA
from app.observability import record


@dataclass(frozen=True)
class Observation:
    id: str
    source_type: str
    source_key: str
    source_observation_id: str
    payload_hash: str
    payload: dict[str, Any]
    original_url: str
    published_at: str | None
    retrieved_at: str


class ObservationStore:
    def __init__(self, database: Database) -> None:
        self._database = database
        with self._database.connect() as connection:
            connection.executescript(LEDGER_SCHEMA)

    def append(
        self,
        *,
        source_type: str,
        source_key: str,
        source_observation_id: str,
        payload: dict[str, Any],
        original_url: str,
        published_at: str | None,
        retrieved_at: str,
    ) -> Observation:
        canonical_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(canonical_payload.encode()).hexdigest()
        identity = "|".join((source_type, source_key, source_observation_id, payload_hash))
        observation_id = "obs_" + hashlib.sha256(identity.encode()).hexdigest()[:24]

        with self._database.connect() as connection:
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO observations (
                    id, source_type, source_key, source_observation_id,
                    payload_hash, payload_json, original_url, published_at, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    source_type,
                    source_key,
                    source_observation_id,
                    payload_hash,
                    canonical_payload,
                    original_url,
                    published_at,
                    retrieved_at,
                ),
            ).rowcount
            row = connection.execute(
                "SELECT * FROM observations WHERE id = ?",
                (observation_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("observation insert failed")
        record(
            "observation",
            observation_id=observation_id,
            source_type=source_type,
            inserted=inserted > 0,
        )
        return self._row(row)

    def list_for_source_observation(
        self,
        *,
        source_type: str,
        source_key: str,
        source_observation_id: str,
    ) -> list[Observation]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM observations
                WHERE source_type = ? AND source_key = ? AND source_observation_id = ?
                ORDER BY retrieved_at, id
                """,
                (source_type, source_key, source_observation_id),
            ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row) -> Observation:
        return Observation(
            id=row["id"],
            source_type=row["source_type"],
            source_key=row["source_key"],
            source_observation_id=row["source_observation_id"],
            payload_hash=row["payload_hash"],
            payload=json.loads(row["payload_json"]),
            original_url=row["original_url"],
            published_at=row["published_at"],
            retrieved_at=row["retrieved_at"],
        )
