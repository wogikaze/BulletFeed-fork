from __future__ import annotations

import json

from app.database import Database
from app.stores.claim_ledger_store import ClaimLedgerStore
from app.stores.observation_store import Observation

_ALIAS_SCHEMA = """
CREATE TABLE IF NOT EXISTS github_advisory_alias_evidence (
    observation_id TEXT PRIMARY KEY,
    alias_ghsa_id TEXT NOT NULL,
    canonical_ghsa_id TEXT NOT NULL,
    attached_claim_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(observation_id) REFERENCES observations(id),
    FOREIGN KEY(attached_claim_id) REFERENCES state_claims(id)
);
CREATE INDEX IF NOT EXISTS idx_github_advisory_alias_canonical
ON github_advisory_alias_evidence(canonical_ghsa_id, attached_claim_id);
"""


class GitHubAdvisoryAliasStore:
    """Keep withdrawn duplicate advisories as evidence for the canonical GHSA."""

    def __init__(self, database: Database, ledger: ClaimLedgerStore) -> None:
        self._database = database
        self._ledger = ledger
        with self._database.connect() as connection:
            connection.executescript(_ALIAS_SCHEMA)

    def record(
        self,
        observation: Observation,
        *,
        alias_ghsa_id: str,
        canonical_ghsa_id: str,
    ) -> tuple[str, str] | None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO github_advisory_alias_evidence (
                    observation_id, alias_ghsa_id, canonical_ghsa_id, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(observation_id) DO UPDATE SET
                    alias_ghsa_id = excluded.alias_ghsa_id,
                    canonical_ghsa_id = excluded.canonical_ghsa_id
                """,
                (
                    observation.id,
                    alias_ghsa_id,
                    canonical_ghsa_id,
                    observation.retrieved_at,
                ),
            )
        claim = self._find_canonical_claim(canonical_ghsa_id)
        if claim is None:
            return None
        self._attach(observation, claim_id=claim[0])
        return claim

    def attach_pending(self, *, canonical_ghsa_id: str, claim_id: str) -> int:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.*
                FROM github_advisory_alias_evidence a
                JOIN observations o ON o.id = a.observation_id
                WHERE a.canonical_ghsa_id = ? AND a.attached_claim_id IS NULL
                ORDER BY o.retrieved_at, o.id
                """,
                (canonical_ghsa_id,),
            ).fetchall()
        for row in rows:
            self._attach(self._observation(row), claim_id=claim_id)
        return len(rows)

    def _find_canonical_claim(self, canonical_ghsa_id: str) -> tuple[str, str] | None:
        canonical_source_event_id = f"canonical:github-advisory:{canonical_ghsa_id.upper()}"
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT c.id AS claim_id, c.event_id
                FROM ledger_events e
                JOIN state_claims c ON c.event_id = e.id
                JOIN claim_relations r ON r.new_claim_id = c.id
                WHERE e.source_type = 'github_advisory'
                  AND e.source_event_id IN (?, ?)
                  AND c.slot = 'advisory_state'
                  AND r.relation_type != 'UNRESOLVED_CONTRADICTION'
                ORDER BY c.valid_at DESC, c.source_updated_at DESC, c.id DESC
                LIMIT 1
                """,
                (canonical_ghsa_id, canonical_source_event_id),
            ).fetchone()
        if row is None:
            return None
        return row["claim_id"], row["event_id"]

    def _attach(self, observation: Observation, *, claim_id: str) -> None:
        payload = observation.payload
        summary = payload.get("summary") if isinstance(payload.get("summary"), str) else ""
        evidence_text = summary.strip() or f"Duplicate advisory {observation.source_observation_id}."
        self._ledger.add_evidence(claim_id, observation, evidence_text=evidence_text)
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE github_advisory_alias_evidence
                SET attached_claim_id = ?
                WHERE observation_id = ?
                """,
                (claim_id, observation.id),
            )

    @staticmethod
    def _observation(row) -> Observation:
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
