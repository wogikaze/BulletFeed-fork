from __future__ import annotations

from datetime import UTC, datetime

from app.config import Settings
from app.database import Database
from app.services import statuspage
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspageIngestResult, StatuspagePipeline


class StatuspageCrawler:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    async def crawl_page(self, page_id: str) -> StatuspageIngestResult:
        summary = await statuspage.get_summary(self._settings, page_id)
        retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        result = StatuspagePipeline(self._database).ingest_summary(
            page_id=page_id,
            summary=summary,
            retrieved_at=retrieved_at,
        )
        projector = LedgerProjector(self._database)
        for event_id in result.event_ids:
            projector.project_event(event_id)
        return result
