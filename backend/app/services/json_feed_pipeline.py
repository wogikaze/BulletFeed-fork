from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.database import Database
from app.services.feed_lifecycle import resolve_feed_lifecycle
from app.services.json_feed import fetch_json_feed, normalize_json_feed
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import SourceIngestionPipeline
from app.services.timestamps import canonical_timestamp
from app.stores.claim_ledger_store import ClaimLedgerStore


@dataclass(frozen=True)
class JsonFeedIngestResult:
    event_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]


def ingest_json_feed_events(
    database: Database,
    *,
    feed: dict[str, Any],
    feed_url: str,
    retrieved_at: str,
) -> JsonFeedIngestResult:
    normalized_retrieved_at = canonical_timestamp(retrieved_at) or retrieved_at
    observations = SourceIngestionPipeline(database).ingest_many(
        normalize_json_feed(feed, feed_url=feed_url),
        retrieved_at=normalized_retrieved_at,
    )
    ledger = ClaimLedgerStore(database)
    projector = LedgerProjector(database)
    event_ids: list[str] = []
    claim_ids: list[str] = []
    for observation in observations:
        payload = observation.payload
        title = payload.get("title") if isinstance(payload.get("title"), str) else ""
        summary = payload.get("summary") if isinstance(payload.get("summary"), str) else ""
        content = payload.get("content_text") if isinstance(payload.get("content_text"), str) else ""
        detail = summary.strip() or content.strip() or title.strip() or observation.original_url
        valid_at = (
            canonical_timestamp(payload.get("date_published"))
            or observation.published_at
            or normalized_retrieved_at
        )
        source_updated_at = canonical_timestamp(payload.get("date_modified")) or valid_at
        lifecycle = resolve_feed_lifecycle(title, observation.original_url)
        claim = ledger.ingest(
            observation,
            source_event_id=observation.source_observation_id,
            canonical_event_key=lifecycle.canonical_event_key if lifecycle else None,
            title=lifecycle.subject if lifecycle else title.strip() or observation.original_url,
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
    return JsonFeedIngestResult(
        event_ids=tuple(dict.fromkeys(event_ids)),
        claim_ids=tuple(claim_ids),
    )


async def crawl_json_feed_events(
    settings: Settings,
    database: Database,
    *,
    url: str,
    retrieved_at: str,
) -> JsonFeedIngestResult:
    feed, final_url = await fetch_json_feed(settings, url)
    return ingest_json_feed_events(
        database,
        feed=feed,
        feed_url=final_url,
        retrieved_at=retrieved_at,
    )
