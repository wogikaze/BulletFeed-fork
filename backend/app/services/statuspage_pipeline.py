from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database import Database
from app.services.statuspage_incidents import normalize_incident_updates
from app.stores.incident_ledger_store import IncidentLedgerStore, IncidentState


@dataclass(frozen=True)
class StatuspageIngestResult:
    event_ids: tuple[str, ...]
    claims: tuple[IncidentState, ...]


class StatuspagePipeline:
    def __init__(self, database: Database) -> None:
        self._ledger = IncidentLedgerStore(database)

    def ingest_summary(
        self,
        *,
        page_id: str,
        summary: dict[str, Any],
        retrieved_at: str,
    ) -> StatuspageIngestResult:
        states = tuple(
            self._ledger.ingest(item, retrieved_at=retrieved_at)
            for item in normalize_incident_updates(page_id, summary)
        )
        event_ids = tuple(dict.fromkeys(state.event_id for state in states))
        return StatuspageIngestResult(event_ids=event_ids, claims=states)
