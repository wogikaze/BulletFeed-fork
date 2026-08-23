from __future__ import annotations

from typing import Any

from app.config import Settings
from app.database import Database
from app.services.rss import preview_feed
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.services.timestamps import canonical_timestamp


def normalize_feed_preview(preview: dict[str, Any]) -> tuple[NormalizedObservation, ...]:
    source_url = preview.get("source_url")
    items = preview.get("items")
    if not isinstance(source_url, str) or not isinstance(items, list):
        return ()

    observations: list[NormalizedObservation] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if not isinstance(link, str) or not link:
            continue
        observations.append(
            NormalizedObservation(
                source_type="rss_atom",
                source_key=source_url,
                source_observation_id=link,
                payload=item,
                original_url=link,
                published_at=canonical_timestamp(item.get("published")),
            )
        )
    return tuple(observations)


async def crawl_feed(
    settings: Settings,
    database: Database,
    *,
    url: str,
    retrieved_at: str,
):
    preview = await preview_feed(settings, url)
    observations = normalize_feed_preview(preview)
    return SourceIngestionPipeline(database).ingest_many(observations, retrieved_at=retrieved_at)
