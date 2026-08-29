from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from app.database import Database
from app.db.event_identity_schema import ensure_event_identity_schema
from app.db.state_ledger_schema import STATE_LEDGER_SCHEMA
from app.services.event_coreference import CoreferenceInput, EventCoreferenceEngine
from app.services.semantic_delta import ClaimSnapshot, DeltaContext, judge_revision
from app.services.source_catalog import source_allows_claim_evidence
from app.services.source_dependence import evidence_dependence_key
from app.stores.observation_store import Observation


@dataclass(frozen=True)
class LedgerClaim:
    event_id: str
    claim_id: str
    slot: str
    value: str
    detail: str
    valid_at: str
    source_updated_at: str
    relation_type: str


class ClaimLedgerStore:
    """Persist source-neutral event claims derived from immutable observations."""

    def __init__(self, database: Database) -> None:
        self._database = database
        with self._database.connect() as connection:
            connection.executescript(STATE_LEDGER_SCHEMA)
        ensure_event_identity_schema(database)

    def ingest(
        self,
        observation: Observation,
        *,
        source_event_id: str,
        title: str,
        slot: str,
        value: str,
        detail: str,
        valid_at: str,
        evidence_text: str,
        source_updated_at: str | None = None,
        explicit_correction: bool = False,
        unresolved_source_conflict: bool = False,
        canonical_event_key: str | None = None,
        coreference_subject: str | None = None,
        coreference_user_id: str | None = None,
    ) -> LedgerClaim:
        self._require_evidence_source(observation)
        if explicit_correction and unresolved_source_conflict:
            raise ValueError("a claim cannot be both an explicit correction and an unresolved conflict")

        source_updated_at = source_updated_at or valid_at
        revision_hint = self._revision_hint(
            explicit_correction=explicit_correction,
            unresolved_source_conflict=unresolved_source_conflict,
        )
        stored_source_event_id = source_event_id
        event_id: str
        if canonical_event_key:
            event_identity = f"canonical|{canonical_event_key}"
            stored_source_event_id = f"canonical:{canonical_event_key}"
            event_id = self._stable_id("evt", event_identity)
        else:
            coreference = EventCoreferenceEngine(self._database)
            incoming = CoreferenceInput(
                source_type=observation.source_type,
                source_key=observation.source_key,
                source_event_id=source_event_id,
                title=title,
                subject=coreference_subject or "",
                valid_at=valid_at,
            )
            alias_event_id = coreference.resolve_alias(
                incoming.alias_key,
                user_id=coreference_user_id,
            )
            if alias_event_id is not None:
                event_id = alias_event_id
            elif coreference_subject is not None:
                decision = coreference.resolve(incoming, user_id=coreference_user_id)
                if decision.label == "same_event" and decision.candidate_event_id is not None:
                    event_id = decision.candidate_event_id
                    coreference.record_alias(
                        incoming.alias_key,
                        event_id,
                        reason=decision.reason,
                        created_at=observation.retrieved_at,
                        decision_version=decision.version,
                    )
                else:
                    event_id = self._native_event_id(observation, source_event_id)
            else:
                event_id = self._native_event_id(observation, source_event_id)

        claim_identity = "|".join(
            (event_id, observation.id, slot, value, detail, valid_at, source_updated_at)
        )
        claim_id = self._stable_id("clm", claim_identity)

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO ledger_events (
                    id, source_type, source_key, source_event_id, title, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    observation.source_type,
                    observation.source_key,
                    stored_source_event_id,
                    title,
                    valid_at,
                ),
            )
            existing = connection.execute(
                "SELECT id, revision_hint FROM state_claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO state_claims (
                        id, event_id, observation_id, slot, value_text, detail_text,
                        valid_at, source_updated_at, revision_hint, observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        event_id,
                        observation.id,
                        slot,
                        value,
                        detail,
                        valid_at,
                        source_updated_at,
                        revision_hint,
                        observation.retrieved_at,
                    ),
                )
                self._insert_evidence(connection, claim_id, observation, evidence_text)
                self._rebuild_relations(connection, event_id, slot)
            elif existing["revision_hint"] != revision_hint:
                raise ValueError("the same immutable claim was ingested with conflicting revision hints")

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

        return LedgerClaim(
            event_id=event_id,
            claim_id=claim_id,
            slot=row["slot"],
            value=row["value_text"],
            detail=row["detail_text"],
            valid_at=row["valid_at"],
            source_updated_at=row["source_updated_at"],
            relation_type=row["relation_type"],
        )

    def add_evidence(
        self,
        claim_id: str,
        observation: Observation,
        *,
        evidence_text: str,
    ) -> str:
        """Attach another immutable Observation as support for an existing Claim."""
        self._require_evidence_source(observation)
        with self._database.connect() as connection:
            claim = connection.execute(
                "SELECT id FROM state_claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
            if claim is None:
                raise ValueError(f"claim {claim_id} not found")
            return self._insert_evidence(connection, claim_id, observation, evidence_text)

    def independent_evidence_count(self, claim_id: str) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(DISTINCT dependence_key) AS count
                FROM claim_evidence
                WHERE claim_id = ?
                """,
                (claim_id,),
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def rebuild_event_relations(self, event_id: str) -> None:
        with self._database.connect() as connection:
            slots = [
                row["slot"]
                for row in connection.execute(
                    "SELECT DISTINCT slot FROM state_claims WHERE event_id = ? ORDER BY slot",
                    (event_id,),
                ).fetchall()
            ]
            connection.execute("DELETE FROM claim_relations WHERE event_id = ?", (event_id,))
            for slot in slots:
                self._rebuild_relations(connection, event_id, slot)

    def _insert_evidence(
        self,
        connection: sqlite3.Connection,
        claim_id: str,
        observation: Observation,
        evidence_text: str,
    ) -> str:
        evidence_id = self._stable_id("evd", f"{claim_id}|{observation.id}")
        dependence_key = evidence_dependence_key(observation)
        connection.execute(
            """
            INSERT OR IGNORE INTO claim_evidence (
                id, claim_id, observation_id, original_url, evidence_text,
                dependence_key, published_at, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                claim_id,
                observation.id,
                observation.original_url,
                evidence_text,
                dependence_key,
                observation.published_at,
                observation.retrieved_at,
            ),
        )
        return evidence_id

    def _rebuild_relations(self, connection: sqlite3.Connection, event_id: str, slot: str) -> None:
        claims = connection.execute(
            """
            SELECT * FROM state_claims
            WHERE event_id = ? AND slot = ?
            ORDER BY valid_at, source_updated_at, id
            """,
            (event_id, slot),
        ).fetchall()
        connection.execute(
            """
            DELETE FROM claim_relations
            WHERE event_id = ?
              AND new_claim_id IN (
                  SELECT id FROM state_claims WHERE event_id = ? AND slot = ?
              )
            """,
            (event_id, event_id, slot),
        )

        settled_prior = None
        for claim in claims:
            decision = judge_revision(
                self._snapshot(settled_prior) if settled_prior is not None else None,
                self._snapshot(claim),
                context=DeltaContext(
                    explicit_correction=claim["revision_hint"] == "correction",
                    unresolved_source_conflict=claim["revision_hint"] == "unresolved_conflict",
                ),
            )
            relation_type = decision.revision_type
            relation_id = self._stable_id(
                "rel",
                f"{claim['id']}|{relation_type}|{settled_prior['id'] if settled_prior is not None else ''}",
            )
            connection.execute(
                """
                INSERT INTO claim_relations (
                    id, event_id, prior_claim_id, new_claim_id, relation_type, occurred_at,
                    decision_reason, decision_confidence, decision_version, decision_abstained
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relation_id,
                    event_id,
                    settled_prior["id"] if settled_prior is not None else None,
                    claim["id"],
                    relation_type,
                    claim["valid_at"],
                    decision.reason,
                    decision.confidence,
                    decision.version,
                    int(decision.abstained),
                ),
            )
            if relation_type != "UNRESOLVED_CONTRADICTION":
                settled_prior = claim

    @staticmethod
    def _revision_hint(*, explicit_correction: bool, unresolved_source_conflict: bool) -> str:
        if explicit_correction:
            return "correction"
        if unresolved_source_conflict:
            return "unresolved_conflict"
        return ""

    @staticmethod
    def _require_evidence_source(observation: Observation) -> None:
        if not source_allows_claim_evidence(observation.source_type):
            raise ValueError(
                f"source type {observation.source_type!r} is not eligible for claim evidence"
            )

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> ClaimSnapshot:
        return ClaimSnapshot(
            value=row["value_text"],
            detail=row["detail_text"],
            valid_at=row["valid_at"],
        )

    @classmethod
    def _native_event_id(cls, observation: Observation, source_event_id: str) -> str:
        return cls._stable_id(
            "evt",
            "|".join((observation.source_type, observation.source_key, source_event_id)),
        )

    @staticmethod
    def _stable_id(prefix: str, raw: str) -> str:
        return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
