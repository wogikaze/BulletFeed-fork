"""Acquire source-discovery candidates from GitHub search without reading gold.

The collector accepts only topic strings. It first searches an organization
whose name matches the topic's publisher token (for example ``Python`` ->
``python``), then falls back to broad repository search when that scope is
empty. Search results are recorded without hand-picking against evaluation
labels.

For each non-fork, non-archived repository we emit its releases endpoint and,
when GitHub metadata exposes a public project homepage, run the production
site/feed discovery path against that homepage. Well-known path probing is
disabled here to keep live acquisition bounded; explicit HTML feed links and
the generic-web fallback are retained.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.evaluation.source_discovery_independent import (
    INDEPENDENT_CANDIDATE_VERSION,
    IndependentCandidate,
    IndependentCandidateArtifact,
)
from app.services.http import require_json
from app.services.source_catalog import SourceKind
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_feed_discover import discover_feeds_from_site_url
from app.services.source_registry import canonicalize_url
from app.services.url_safety import validate_url_shape
from app.services.user_interest import resolve_concept_id
from app.services.user_source_grants import settings_for_site_discovery

TOPIC_INPUT_VERSION = "source-discovery-topic-input-v0.1"
COLLECTOR_VERSION = "github-independent-collector-v0.1"
_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
_DEFAULT_REPOSITORIES_PER_TOPIC = 3
_MAX_REPOSITORIES_PER_TOPIC = 5
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDiscoveryTopicInput(_StrictModel):
    artifact_version: Literal["source-discovery-topic-input-v0.1"]
    topics: list[str] = Field(min_length=1)


def validate_topic_input(value: SourceDiscoveryTopicInput) -> None:
    cleaned = [topic.strip() for topic in value.topics]
    if any(not topic for topic in cleaned):
        raise ValueError("source-discovery topics must be non-empty")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("source-discovery topics must be unique")
    if cleaned != value.topics:
        raise ValueError("source-discovery topics must already be trimmed")


def publisher_token(topic: str) -> str:
    """Return a deterministic publisher-shaped token from a topic string."""
    parts = _TOKEN_PATTERN.findall(topic.casefold())
    if parts:
        return parts[0]
    concept = resolve_concept_id(topic).strip().casefold()
    token = concept.split("-", 1)[0]
    if not token:
        raise ValueError("topic does not contain a publisher token")
    return token


async def collect_github_independent_candidates(
    settings: Settings,
    topic_input: SourceDiscoveryTopicInput,
    *,
    token: str | None = None,
    repositories_per_topic: int = _DEFAULT_REPOSITORIES_PER_TOPIC,
) -> IndependentCandidateArtifact:
    """Collect a recorded-external artifact from topic-only acquisition input."""
    validate_topic_input(topic_input)
    limit = max(1, min(int(repositories_per_topic), _MAX_REPOSITORIES_PER_TOPIC))
    items: list[IndependentCandidate] = []
    for topic in topic_input.topics:
        concept_id = resolve_concept_id(topic)
        repos, evidence_reference = await _search_topic_repositories(
            settings,
            topic,
            token=token,
            limit=limit,
        )
        for repo in repos:
            items.extend(
                await _candidates_from_repository(
                    settings,
                    topic=topic,
                    concept_id=concept_id,
                    repository=repo,
                    search_evidence_reference=evidence_reference,
                )
            )
    deduplicated: dict[tuple[str, str, tuple[str, ...]], IndependentCandidate] = {}
    for item in items:
        key = (item.family, item.url, tuple(item.concept_ids))
        deduplicated.setdefault(key, item)
    return IndependentCandidateArtifact(
        artifact_version=INDEPENDENT_CANDIDATE_VERSION,
        acquisition_mode="recorded_external",
        gold_read=False,
        collector_version=COLLECTOR_VERSION,
        items=list(deduplicated.values()),
    )


async def _search_topic_repositories(
    settings: Settings,
    topic: str,
    *,
    token: str | None,
    limit: int,
) -> tuple[tuple[dict[str, Any], ...], str]:
    org = publisher_token(topic)
    scoped_query = f"{topic} org:{org}"
    scoped = await _search_repositories(settings, scoped_query, token=token, limit=limit)
    scoped = _eligible_repositories(scoped, limit=limit)
    if scoped:
        return scoped, _search_reference(scoped_query, limit)

    broad = await _search_repositories(settings, topic, token=token, limit=limit)
    return _eligible_repositories(broad, limit=limit), _search_reference(topic, limit)


async def _search_repositories(
    settings: Settings,
    query: str,
    *,
    token: str | None,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": settings.crawler_user_agent,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        trust_env=False,
    ) as client:
        response = await client.get(
            _GITHUB_SEARCH_URL,
            headers=headers,
            params={
                "q": query,
                "per_page": limit,
                "page": 1,
            },
        )
    payload = await require_json(response, "GitHub repository search")
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise HTTPException(status_code=502, detail="GitHub repository search returned invalid data")
    return tuple(item for item in payload["items"] if isinstance(item, dict))


def _eligible_repositories(
    repositories: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in repositories:
        full_name = raw.get("full_name")
        if not isinstance(full_name, str) or full_name.count("/") != 1:
            continue
        normalized = full_name.strip()
        if not normalized or normalized.casefold() in seen:
            continue
        if bool(raw.get("fork")) or bool(raw.get("archived")):
            continue
        seen.add(normalized.casefold())
        selected.append(dict(raw))
        if len(selected) >= limit:
            break
    return tuple(selected)


async def _candidates_from_repository(
    settings: Settings,
    *,
    topic: str,
    concept_id: str,
    repository: Mapping[str, Any],
    search_evidence_reference: str,
) -> tuple[IndependentCandidate, ...]:
    full_name = str(repository["full_name"]).strip()
    owner, _ = full_name.split("/", 1)
    html_url = repository.get("html_url")
    repo_url = (
        html_url.strip()
        if isinstance(html_url, str) and html_url.strip()
        else f"https://github.com/{full_name}"
    )
    try:
        canonical_repo = canonicalize_url(repo_url)
    except ValueError:
        canonical_repo = canonicalize_url(f"https://github.com/{full_name}")
    releases_url = canonicalize_url(f"https://github.com/{full_name}/releases")
    release = IndependentCandidate(
        url=releases_url,
        family=SourceKind.GITHUB_RELEASE.value,
        concept_ids=[concept_id],
        provenance=DiscoveryProvenance.REPOSITORY_METADATA.value,
        title=f"{full_name} releases",
        publisher_slug=owner.casefold(),
        publisher_name=full_name,
        homepage_url=canonical_repo,
        why=f"Repository returned by GitHub search for topic {topic}",
        display_name=f"{full_name} releases",
        observed_via="github_repository_search",
        evidence_reference=search_evidence_reference,
    )
    candidates: list[IndependentCandidate] = [release]

    homepage = _public_project_homepage(repository.get("homepage"))
    if homepage is None:
        return tuple(candidates)
    try:
        discovery_settings = settings_for_site_discovery(settings, homepage)
        discovered = await discover_feeds_from_site_url(
            discovery_settings,
            homepage,
            persist_registry=False,
            probe_well_known=False,
        )
    except (HTTPException, ValueError):
        return tuple(candidates)
    except Exception:  # noqa: BLE001 - optional external homepage enrichment
        # The repository candidate remains valid evidence that acquisition ran.
        return tuple(candidates)

    for item in discovered.items:
        candidates.append(
            IndependentCandidate(
                url=canonicalize_url(item.canonical_url),
                family=item.family,
                concept_ids=[concept_id],
                provenance=DiscoveryProvenance.WEBSITE_FEED.value,
                title=item.title,
                publisher_slug=item.publisher_slug,
                publisher_name=item.publisher_display_name,
                homepage_url=canonicalize_url(homepage),
                why=f"Project homepage discovered from GitHub repository {full_name}",
                display_name=item.title,
                observed_via="github_repository_homepage_feed_discovery",
                evidence_reference=canonical_repo,
            )
        )
    return tuple(candidates)


def _public_project_homepage(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = validate_url_shape(raw, source_name="GitHub repository homepage")
    except HTTPException:
        return None
    host = (parsed.hostname or "").casefold().rstrip(".")
    if not host or host == "github.com" or host.endswith(".github.com"):
        return None
    try:
        return canonicalize_url(raw)
    except ValueError:
        return None


def _search_reference(query: str, limit: int) -> str:
    params = {
        "q": query,
        "per_page": limit,
        "page": 1,
    }
    return f"{_GITHUB_SEARCH_URL}?{urlencode(params)}"
