from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings
from app.database import Database
from app.services.http import require_json
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline

HN_API = "https://hacker-news.firebaseio.com/v0"


async def fetch_top_story_items(settings: Settings, *, limit: int = 30) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(f"{HN_API}/topstories.json")
        ids = await require_json(response, "Hacker News")
        if not isinstance(ids, list):
            return []
        items: list[dict[str, Any]] = []
        for story_id in ids[:limit]:
            if not isinstance(story_id, int):
                continue
            item_response = await client.get(f"{HN_API}/item/{story_id}.json")
            item = await require_json(item_response, "Hacker News")
            if isinstance(item, dict):
                items.append(item)
        return items


def normalize_hacker_news_candidates(items: list[dict[str, Any]]) -> tuple[NormalizedObservation, ...]:
    observations: list[NormalizedObservation] = []
    for item in items:
        story_id = item.get("id")
        if not isinstance(story_id, int):
            continue
        outbound_url = item.get("url")
        original_url = (
            outbound_url
            if isinstance(outbound_url, str) and outbound_url
            else f"https://news.ycombinator.com/item?id={story_id}"
        )
        published_at = None
        timestamp = item.get("time")
        if isinstance(timestamp, int):
            published_at = (
                datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")
            )
        observations.append(
            NormalizedObservation(
                source_type="hacker_news_discovery",
                source_key="topstories",
                source_observation_id=str(story_id),
                payload=item,
                original_url=original_url,
                published_at=published_at,
            )
        )
    return tuple(observations)


async def crawl_hacker_news_discovery(
    settings: Settings,
    database: Database,
    *,
    retrieved_at: str,
    limit: int = 30,
):
    items = await fetch_top_story_items(settings, limit=limit)
    observations = normalize_hacker_news_candidates(items)
    return SourceIngestionPipeline(database).ingest_many(observations, retrieved_at=retrieved_at)
