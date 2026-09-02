from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.database import Database
from app.observability import record
from app.services.feed_lifecycle import resolve_feed_lifecycle
from app.services.ledger_projection import LedgerProjector
from app.services.rss import preview_feed
from app.services.rss_article_enrichment import format_claim_evidence, is_summary_only
from app.services.rss_source import normalize_feed_preview
from app.services.source_ingestion import SourceIngestionPipeline
from app.services.source_subscriptions import project_events_for_subscription_audience
from app.services.timestamps import canonical_timestamp
from app.stores.claim_ledger_store import ClaimLedgerStore

# Worker-path cap. The G4 live harness still calls enrich_feed_item per item.
MAX_ARTICLE_FETCHES_PER_FEED = 3


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
        article_text = payload.get("article_text") if isinstance(payload.get("article_text"), str) else ""
        locator = (
            payload.get("evidence_locator") if isinstance(payload.get("evidence_locator"), str) else ""
        )
        detail = article_text.strip() or summary.strip() or title.strip()
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
            evidence_text=format_claim_evidence(detail=detail, evidence_locator=locator),
        )
        projector.project_event(claim.event_id)
        event_ids.append(claim.event_id)
        claim_ids.append(claim.claim_id)

    unique_event_ids = tuple(dict.fromkeys(event_ids))
    source_url = preview.get("source_url") if isinstance(preview.get("source_url"), str) else ""
    items = preview.get("items")
    if source_url and isinstance(items, list):
        from app.services.index_publisher_discovery import publisher_feed_hints_from_index_preview
        from app.services.japanese_source_catalog import japanese_broad_tech_concepts
        from app.services.source_discovery_runtime import persist_runtime_discovery_hints

        persist_runtime_discovery_hints(
            database,
            publisher_feed_hints_from_index_preview(
                items,
                index_url=source_url,
                concept_ids=japanese_broad_tech_concepts(),
            ),
            persist_registry=False,
        )
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
    items = preview.get("items")
    if isinstance(items, list):
        from app.services.rss_article_enrichment import enrich_feed_item

        enriched = []
        article_fetches = 0
        for item in items:
            if not isinstance(item, dict):
                enriched.append(item)
                continue
            summary = item.get("summary") if isinstance(item.get("summary"), str) else ""
            feed_body = item.get("content") if isinstance(item.get("content"), str) else ""
            link = item.get("link") if isinstance(item.get("link"), str) else ""
            needs_fetch = bool(link) and is_summary_only(summary, feed_body=feed_body)
            if needs_fetch and article_fetches >= MAX_ARTICLE_FETCHES_PER_FEED:
                enriched.append({**item, "article_fetch_skipped": True})
                continue
            enriched.append(await enrich_feed_item(settings, item, retrieved_at=retrieved_at))
            if needs_fetch:
                article_fetches += 1
        preview = {**preview, "items": enriched}
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
