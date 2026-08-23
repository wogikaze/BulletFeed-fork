from __future__ import annotations

from typing import Any

from app.config import Settings
from app.database import Database
from app.services.github import list_global_advisories
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline


def normalize_github_advisories(
    advisories: list[dict[str, Any]],
    *,
    ecosystem: str | None = None,
) -> tuple[NormalizedObservation, ...]:
    source_key = ecosystem or "global"
    observations: list[NormalizedObservation] = []
    for advisory in advisories:
        ghsa_id = advisory.get("ghsa_id")
        if not isinstance(ghsa_id, str) or not ghsa_id:
            continue
        html_url = advisory.get("html_url")
        if not isinstance(html_url, str) or not html_url:
            html_url = f"https://github.com/advisories/{ghsa_id}"
        published_at = advisory.get("published_at") or advisory.get("updated_at")
        observations.append(
            NormalizedObservation(
                source_type="github_advisory",
                source_key=source_key,
                source_observation_id=ghsa_id,
                payload=advisory,
                original_url=html_url,
                published_at=published_at if isinstance(published_at, str) else None,
            )
        )
    return tuple(observations)


async def crawl_github_advisories(
    settings: Settings,
    database: Database,
    *,
    retrieved_at: str,
    ecosystem: str | None = None,
    token: str | None = None,
):
    advisories = await list_global_advisories(
        settings,
        ecosystem=ecosystem,
        token=token,
    )
    observations = normalize_github_advisories(advisories, ecosystem=ecosystem)
    return SourceIngestionPipeline(database).ingest_many(observations, retrieved_at=retrieved_at)
