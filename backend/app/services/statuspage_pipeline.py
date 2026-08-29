from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database import Database
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_incidents import StatuspageIncidentObservation, normalize_incident_updates
from app.stores.claim_ledger_store import ClaimLedgerStore, LedgerClaim
from app.stores.observation_store import Observation, ObservationStore


@dataclass(frozen=True)
class StatuspageIngestResult:
    event_ids: tuple[str, ...]
    claims: tuple[LedgerClaim, ...]


def ingest_statuspage_item(
    ledger: ClaimLedgerStore,
    observations: ObservationStore,
    item: StatuspageIncidentObservation,
    *,
    retrieved_at: str,
) -> LedgerClaim:
    """Append one Statuspage update, then judge it through ClaimLedgerStore."""
    observation = observations.append(
        source_type="statuspage",
        source_key=item.page_id,
        source_observation_id=item.update_id,
        payload=item.raw,
        original_url=item.original_url,
        published_at=item.published_at,
        retrieved_at=retrieved_at,
    )
    return claim_from_statuspage_observation(ledger, observation, item)


def claim_from_statuspage_observation(
    ledger: ClaimLedgerStore,
    observation: Observation,
    item: StatuspageIncidentObservation,
) -> LedgerClaim:
    return ledger.ingest(
        observation,
        source_event_id=item.incident_id,
        title=item.incident_name,
        slot="incident_status",
        value=item.status,
        detail=item.body,
        valid_at=item.published_at,
        source_updated_at=item.updated_at,
        evidence_text=item.body,
        explicit_correction=item.explicit_correction,
    )


class StatuspagePipeline:
    def __init__(self, database: Database) -> None:
        self._observations = ObservationStore(database)
        self._ledger = ClaimLedgerStore(database)
        self._projector = LedgerProjector(database)

    def ingest_summary(
        self,
        *,
        page_id: str,
        summary: dict[str, Any],
        retrieved_at: str,
    ) -> StatuspageIngestResult:
        claims = tuple(
            self._ingest_item(item, retrieved_at=retrieved_at)
            for item in normalize_incident_updates(page_id, summary)
        )
        event_ids = tuple(dict.fromkeys(claim.event_id for claim in claims))
        return StatuspageIngestResult(event_ids=event_ids, claims=claims)

    def _ingest_item(
        self,
        item: StatuspageIncidentObservation,
        *,
        retrieved_at: str,
    ) -> LedgerClaim:
        claim = ingest_statuspage_item(
            self._ledger,
            self._observations,
            item,
            retrieved_at=retrieved_at,
        )
        self._projector.project_event(claim.event_id)
        return claim
