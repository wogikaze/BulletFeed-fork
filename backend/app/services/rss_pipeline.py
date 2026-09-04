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
from app.services.user_source_grants import settings_for_active_source
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
    source_url = preview.get("source_url") if isinstance(preview.get("source_url"), str) else ""
    retrieved_stamp = canonical_timestamp(retrieved_at) or retrieved_at
    from app.services.index_publisher_discovery import is_japanese_index_feed

    if is_japanese_index_feed(source_url):
        items = preview.get("items")
        if isinstance(items, list):
            _persist_index_publisher_hints(
                database,
                items=items,
                index_url=source_url,
                retrieved_at=retrieved_stamp,
            )
        return RssIngestResult(event_ids=(), claim_ids=())

    normalized = normalize_feed_preview(preview)
    observations = SourceIngestionPipeline(database).ingest_many(
        normalized,
        retrieved_at=retrieved_stamp,
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


def _persist_index_publisher_hints(
    database: Database,
    *,
    items: list[Any],
    index_url: str,
    retrieved_at: str,
) -> None:
    from app.services.index_publisher_discovery import publisher_feed_hints_from_index_preview
    from app.services.japanese_source_catalog import japanese_broad_tech_concepts
    from app.services.source_discovery_runtime import persist_runtime_discovery_hints

    try:
        hints = publisher_feed_hints_from_index_preview(
            items,
            index_url=index_url,
            concept_ids=japanese_broad_tech_concepts(),
        )
        if hints:
            persist_runtime_discovery_hints(
                database,
                hints,
                seen_at=retrieved_at,
                persist_registry=False,
            )
    except Exception as exc:  # noqa: BLE001 - discovery is auxiliary to feed ingestion
        record("index_publisher_discovery_failed", error=type(exc).__name__)


async def crawl_feed_events(
    settings: Settings,
    database: Database,
    *,
    url: str,
    retrieved_at: str,
) -> RssIngestResult:
    record("fetch", source_type="rss_atom")
    effective_settings = settings_for_active_source(
        database,
        settings,
        source_type="rss_atom",
        source_key=url,
    )
    preview = await preview_feed(effective_settings, url)
    items = preview.get("items")
    source_url = preview.get("source_url") if isinstance(preview.get("source_url"), str) else url
    from app.services.index_publisher_discovery import is_japanese_index_feed

    if isinstance(items, list) and not is_japanese_index_feed(source_url):
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
            enriched.append(
                await enrich_feed_item(effective_settings, item, retrieved_at=retrieved_at)
            )
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
