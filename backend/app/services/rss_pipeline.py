from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.database import Database
from app.observability import record
from app.services.feed_lifecycle import resolve_feed_lifecycle
from app.services.ledger_projection import LedgerProjector
from app.services.rss import preview_feed
from app.services.rss_source import normalize_feed_preview
from app.services.source_ingestion import SourceIngestionPipeline
from app.services.source_subscriptions import project_events_for_subscription_audience
from app.services.timestamps import canonical_timestamp
from app.stores.claim_ledger_store import ClaimLedgerStore


@dataclass(frozen=True)
class RssIngestResult:
    event_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]


def ingest_feed_events(
    database: Database,
    *,
    preview: dict[str, Any],
    retrieved_at: str,
) -> RssIngestResult:
    normalized = normalize_feed_preview(preview)
    observations = SourceIngestionPipeline(database).ingest_many(
        normalized,
        retrieved_at=canonical_timestamp(retrieved_at) or retrieved_at,
    )
    ledger = ClaimLedgerStore(database)
    projector = LedgerProjector(database)
    event_ids: list[str] = []
    claim_ids: list[str] = []

    for observation in observations:
        payload = observation.payload
        title = payload.get("title") if isinstance(payload.get("title"), str) else observation.original_url
        summary = payload.get("summary") if isinstance(payload.get("summary"), str) else ""
        valid_at = (
            canonical_timestamp(payload.get("published"))
            or observation.published_at
            or canonical_timestamp(retrieved_at)
            or retrieved_at
        )
        source_updated_at = canonical_timestamp(payload.get("updated")) or valid_at
        detail = summary.strip() or title.strip()
        lifecycle = resolve_feed_lifecycle(title, observation.original_url)
        claim = ledger.ingest(
            observation,
            source_event_id=observation.source_observation_id,
            canonical_event_key=lifecycle.canonical_event_key if lifecycle else None,
            title=lifecycle.subject if lifecycle else title.strip(),
            slot=lifecycle.slot if lifecycle else "publication_state",
            value=lifecycle.state if lifecycle else "published",
            detail=detail,
            valid_at=valid_at,
            source_updated_at=source_updated_at,
            evidence_text=detail,
        )
        projector.project_event(claim.event_id)
        event_ids.append(claim.event_id)
        claim_ids.append(claim.claim_id)

    unique_event_ids = tuple(dict.fromkeys(event_ids))
    source_url = preview.get("source_url") if isinstance(preview.get("source_url"), str) else ""
    project_events_for_subscription_audience(
        database,
        source_type="rss_atom",
        source_keys=(source_url,),
        event_ids=unique_event_ids,
    )
    return RssIngestResult(
        event_ids=unique_event_ids,
        claim_ids=tuple(claim_ids),
    )


async def crawl_feed_events(
    settings: Settings,
    database: Database,
    *,
    url: str,
    retrieved_at: str,
) -> RssIngestResult:
    record("fetch", source_type="rss_atom")
    preview = await preview_feed(settings, url)
    result = ingest_feed_events(database, preview=preview, retrieved_at=retrieved_at)
    source_url = preview.get("source_url") if isinstance(preview.get("source_url"), str) else ""
    if url != source_url:
        project_events_for_subscription_audience(
            database,
            source_type="rss_atom",
            source_keys=(url,),
            event_ids=result.event_ids,
        )
    return result
