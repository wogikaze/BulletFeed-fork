from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.database import Database
from app.services.event_access import project_repository_event_access
from app.services.feed_projection import FeedProjector
from app.services.github import list_releases
from app.services.github_release_source import normalize_github_releases
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


@dataclass(frozen=True)
class GitHubReleaseIngestResult:
    event_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]


def ingest_github_release_events(
    database: Database,
    *,
    owner: str,
    repository: str,
    releases: list[dict[str, Any]],
    retrieved_at: str,
) -> GitHubReleaseIngestResult:
    normalized = normalize_github_releases(owner, repository, releases)
    observations = SourceIngestionPipeline(database).ingest_many(
        normalized,
        retrieved_at=retrieved_at,
    )
    ledger = ClaimLedgerStore(database)
    projector = LedgerProjector(database)
    repository_key = f"{owner}/{repository}"
    event_ids: list[str] = []
    claim_ids: list[str] = []

    for observation in observations:
        payload = observation.payload
        release_id = payload["id"]
        tag = payload.get("tag_name") if isinstance(payload.get("tag_name"), str) else ""
        name = payload.get("name") if isinstance(payload.get("name"), str) else ""
        state = (
            "draft"
            if payload.get("draft")
            else "prerelease"
            if payload.get("prerelease")
            else "released"
        )
        valid_at = (
            _timestamp(payload.get("published_at"))
            or _timestamp(payload.get("created_at"))
            or observation.published_at
            or retrieved_at
        )
        source_updated_at = _timestamp(payload.get("updated_at")) or valid_at
        body = payload.get("body") if isinstance(payload.get("body"), str) else ""
        title_suffix = name.strip() or tag.strip() or f"release {release_id}"
        detail = body.strip() or f"{tag or title_suffix} is {state}."
        claim = ledger.ingest(
            observation,
            source_event_id=f"release:{release_id}",
            title=f"{observation.source_key} — {title_suffix}",
            slot="release_state",
            value=state,
            detail=detail,
            valid_at=valid_at,
            source_updated_at=source_updated_at,
            evidence_text=detail,
        )
        projector.project_event(claim.event_id)
        _project_for_watchers(
            database,
            repository_key=repository_key,
            event_id=claim.event_id,
        )
        event_ids.append(claim.event_id)
        claim_ids.append(claim.claim_id)

    return GitHubReleaseIngestResult(
        event_ids=tuple(dict.fromkeys(event_ids)),
        claim_ids=tuple(claim_ids),
    )


def _project_for_watchers(database: Database, *, repository_key: str, event_id: str) -> None:
    user_ids = project_repository_event_access(
        database,
        repository_key=repository_key,
        event_id=event_id,
    )
    feed = FeedProjector(database)
    for user_id in user_ids:
        feed.project_event_for_user(user_id=user_id, event_id=event_id)


async def crawl_github_release_events(
    settings: Settings,
    database: Database,
    *,
    owner: str,
    repository: str,
    retrieved_at: str,
    token: str | None = None,
) -> GitHubReleaseIngestResult:
    releases = await list_releases(settings, owner, repository, token)
    return ingest_github_release_events(
        database,
        owner=owner,
        repository=repository,
        releases=releases,
        retrieved_at=retrieved_at,
    )


def _timestamp(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
