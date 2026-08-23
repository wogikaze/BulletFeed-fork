from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from app.database import Database
from app.db.state_ledger_schema import STATE_LEDGER_SCHEMA
from app.services.semantic_delta import ClaimSnapshot, DeltaContext, classify_revision
from app.services.statuspage_incidents import StatuspageIncidentObservation
from app.stores.observation_store import ObservationStore


@dataclass(frozen=True)
class IncidentState:
    event_id: str
    claim_id: str
    status: str
    detail: str
    valid_at: str
    relation_type: str


class IncidentLedgerStore:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._observations = ObservationStore(database)
        with self._database.connect() as connection:
            connection.executescript(STATE_LEDGER_SCHEMA)

    def ingest(self, item: StatuspageIncidentObservation, *, retrieved_at: str) -> IncidentState:
        observation = self._observations.append(
            source_type="statuspage",
            source_key=item.page_id,
            source_observation_id=item.update_id,
            payload=item.raw,
            original_url=item.original_url,
            published_at=item.published_at,
            retrieved_at=retrieved_at,
        )
        event_id = self._stable_id("evt", item.event_key)
        claim_id = self._stable_id("clm", f"{event_id}|{observation.id}|incident_status|{item.status}")
        evidence_id = self._stable_id("evd", f"{claim_id}|{observation.id}")

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO ledger_events (
                    id, source_type, source_key, source_event_id, title, created_at
                ) VALUES (?, 'statuspage', ?, ?, ?, ?)
                """,
                (event_id, item.page_id, item.incident_id, item.incident_name, item.published_at),
            )
            existing = connection.execute(
                "SELECT * FROM state_claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO state_claims (
                        id, event_id, observation_id, slot, value_text, detail_text,
                        valid_at, source_updated_at, revision_hint, observed_at
                    ) VALUES (?, ?, ?, 'incident_status', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        event_id,
                        observation.id,
                        item.status,
                        item.body,
                        item.published_at,
                        item.updated_at,
                        "correction" if item.explicit_correction else "",
                        retrieved_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO claim_evidence (
                        id, claim_id, observation_id, original_url, evidence_text, published_at, retrieved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        claim_id,
                        observation.id,
                        item.original_url,
                        item.body,
                        item.published_at,
                        retrieved_at,
                    ),
                )
                self._rebuild_relations(connection, event_id)

            row = connection.execute(
                """
                SELECT c.*, r.relation_type
                FROM state_claims c
                JOIN claim_relations r ON r.new_claim_id = c.id
                WHERE c.id = ?
                """,
                (claim_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("claim relation rebuild failed")

        return IncidentState(
            event_id=event_id,
            claim_id=claim_id,
            status=row["value_text"],
            detail=row["detail_text"],
            valid_at=row["valid_at"],
            relation_type=row["relation_type"],
        )

    def history(self, event_id: str) -> list[IncidentState]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.*, r.relation_type
                FROM state_claims c
                JOIN claim_relations r ON r.new_claim_id = c.id
                WHERE c.event_id = ? AND c.slot = 'incident_status'
                ORDER BY c.valid_at, c.source_updated_at, c.id
                """,
                (event_id,),
            ).fetchall()
        return [
            IncidentState(
                event_id=row["event_id"],
                claim_id=row["id"],
                status=row["value_text"],
                detail=row["detail_text"],
                valid_at=row["valid_at"],
                relation_type=row["relation_type"],
            )
            for row in rows
        ]

    def _rebuild_relations(self, connection: sqlite3.Connection, event_id: str) -> None:
        claims = connection.execute(
            """
            SELECT * FROM state_claims
            WHERE event_id = ? AND slot = 'incident_status'
            ORDER BY valid_at, source_updated_at, id
            """,
            (event_id,),
        ).fetchall()
        connection.execute("DELETE FROM claim_relations WHERE event_id = ?", (event_id,))

        prior = None
        for claim in claims:
            relation_type = classify_revision(
                self._snapshot(prior) if prior is not None else None,
                self._snapshot(claim),
                context=DeltaContext(explicit_correction=claim["revision_hint"] == "correction"),
            )
            relation_id = self._stable_id(
                "rel",
                f"{claim['id']}|{relation_type}|{prior['id'] if prior is not None else ''}",
            )
            connection.execute(
                """
                INSERT INTO claim_relations (
                    id, event_id, prior_claim_id, new_claim_id, relation_type, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    relation_id,
                    event_id,
                    prior["id"] if prior is not None else None,
                    claim["id"],
                    relation_type,
                    claim["valid_at"],
                ),
            )
            prior = claim

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> ClaimSnapshot:
        return ClaimSnapshot(
            value=row["value_text"],
            detail=row["detail_text"],
            valid_at=row["valid_at"],
        )

    @staticmethod
    def _stable_id(prefix: str, raw: str) -> str:
        return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
