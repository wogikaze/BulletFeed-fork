from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.database import Database
from app.services.http import require_json
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline

API_URL = "https://api.github.com"


def _headers(settings: Settings, token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": settings.crawler_user_agent,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def fetch_github_sbom(
    settings: Settings,
    *,
    owner: str,
    repository: str,
    token: str | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(
            f"{API_URL}/repos/{owner}/{repository}/dependency-graph/sbom",
            headers=_headers(settings, token),
        )
    data = await require_json(response, "GitHub SBOM")
    if not isinstance(data, dict) or not isinstance(data.get("sbom"), dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub returned invalid SBOM")
    return data


def normalize_github_sbom(owner: str, repository: str, data: dict[str, Any]) -> NormalizedObservation:
    return NormalizedObservation(
        source_type="github_sbom",
        source_key=f"{owner}/{repository}",
        source_observation_id="sbom",
        payload=data,
        original_url=f"https://github.com/{owner}/{repository}",
        published_at=None,
    )


async def crawl_github_sbom(
    settings: Settings,
    database: Database,
    *,
    owner: str,
    repository: str,
    retrieved_at: str,
    token: str | None = None,
):
    data = await fetch_github_sbom(settings, owner=owner, repository=repository, token=token)
    observation = normalize_github_sbom(owner, repository, data)
    return SourceIngestionPipeline(database).ingest_many((observation,), retrieved_at=retrieved_at)
