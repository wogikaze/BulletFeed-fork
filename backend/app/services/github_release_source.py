from __future__ import annotations

from typing import Any

from app.config import Settings
from app.database import Database
from app.services.github import list_releases
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline


def normalize_github_releases(
    owner: str,
    repository: str,
    releases: list[dict[str, Any]],
) -> tuple[NormalizedObservation, ...]:
    source_key = f"{owner}/{repository}"
    items: list[NormalizedObservation] = []
    for release in releases:
        release_id = release.get("id")
        url = release.get("html_url")
        if not isinstance(release_id, int) or not isinstance(url, str) or not url:
            continue
        published_at = release.get("published_at") or release.get("created_at")
        items.append(
            NormalizedObservation(
                source_type="github_release",
                source_key=source_key,
                source_observation_id=f"release:{release_id}",
                payload=release,
                original_url=url,
                published_at=published_at if isinstance(published_at, str) else None,
            )
        )
    return tuple(items)


async def crawl_github_releases(
    settings: Settings,
    database: Database,
    *,
    owner: str,
    repository: str,
    retrieved_at: str,
    token: str | None = None,
):
    releases = await list_releases(settings, owner, repository, token)
    observations = normalize_github_releases(owner, repository, releases)
    return SourceIngestionPipeline(database).ingest_many(observations, retrieved_at=retrieved_at)
