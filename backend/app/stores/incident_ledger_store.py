from __future__ import annotations

from dataclasses import dataclass

from app.database import Database
from app.services.statuspage_incidents import StatuspageIncidentObservation
from app.services.statuspage_pipeline import ingest_statuspage_item
from app.stores.claim_ledger_store import ClaimLedgerStore
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
    """Thin Statuspage adapter over ClaimLedgerStore.

    Observation append and claim identity live here for callers that still ingest
    StatuspageIncidentObservation objects. Revision classification is exclusively
    ClaimLedgerStore.ingest → judge_revision; this adapter has no rebuild path.
    """

    def __init__(self, database: Database) -> None:
        self._database = database
        self._observations = ObservationStore(database)
        self._ledger = ClaimLedgerStore(database)

    def ingest(self, item: StatuspageIncidentObservation, *, retrieved_at: str) -> IncidentState:
        claim = ingest_statuspage_item(
            self._ledger,
            self._observations,
            item,
            retrieved_at=retrieved_at,
        )
        return IncidentState(
            event_id=claim.event_id,
            claim_id=claim.claim_id,
            status=claim.value,
            detail=claim.detail,
            valid_at=claim.valid_at,
            relation_type=claim.relation_type,
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
