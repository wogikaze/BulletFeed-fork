from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.evaluation import source_discovery_github_collector as collector
from app.evaluation.source_discovery_github_collector import (
    SourceDiscoveryTopicInput,
    _candidates_from_repository,
    _eligible_repositories,
    _search_topic_repositories,
    publisher_token,
    validate_topic_input,
)
from app.services.source_catalog import SourceKind
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.user_interest import resolve_concept_id


def test_publisher_token_comes_only_from_topic_text() -> None:
    assert publisher_token("React") == "react"
    assert publisher_token("OpenAI API") == "openai"
    assert publisher_token("Cloudflare Workers") == "cloudflare"


def test_topic_input_is_strict_and_requires_trimmed_unique_topics() -> None:
    value = SourceDiscoveryTopicInput(
        artifact_version="source-discovery-topic-input-v0.1",
        topics=["Python", "React"],
    )
    validate_topic_input(value)

    with pytest.raises(ValueError, match="unique"):
        validate_topic_input(
            SourceDiscoveryTopicInput(
                artifact_version="source-discovery-topic-input-v0.1",
                topics=["React", "React"],
            )
        )
    with pytest.raises(ValidationError):
        SourceDiscoveryTopicInput.model_validate(
            {
                "artifact_version": "source-discovery-topic-input-v0.1",
                "topics": ["React"],
                "expected_urls": ["https://react.dev/rss.xml"],
            }
        )


def test_repository_filter_is_objective_and_stable() -> None:
    rows = (
        {"full_name": "org/primary", "fork": False, "archived": False},
        {"full_name": "org/fork", "fork": True, "archived": False},
        {"full_name": "org/old", "fork": False, "archived": True},
        {"full_name": "ORG/PRIMARY", "fork": False, "archived": False},
        {"full_name": "org/second", "fork": False, "archived": False},
    )
    selected = _eligible_repositories(rows, limit=3)
    assert [row["full_name"] for row in selected] == ["org/primary", "org/second"]


@pytest.mark.asyncio
async def test_search_prefers_same_name_org_and_avoids_broad_fallback(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_search(settings, query, *, token, limit):
        del settings, token, limit
        calls.append(query)
        return ({"full_name": "python/cpython", "fork": False, "archived": False},)

    monkeypatch.setattr(collector, "_search_repositories", fake_search)
    repos, evidence = await _search_topic_repositories(
        Settings(),
        "Python",
        token=None,
        limit=3,
    )
    assert [row["full_name"] for row in repos] == ["python/cpython"]
    assert calls == ["Python org:python"]
    assert "org%3Apython" in evidence


@pytest.mark.asyncio
async def test_search_falls_back_to_broad_when_org_scope_is_empty(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_search(settings, query, *, token, limit):
        del settings, token, limit
        calls.append(query)
        if "org:" in query:
            return ()
        return ({"full_name": "example/react", "fork": False, "archived": False},)

    monkeypatch.setattr(collector, "_search_repositories", fake_search)
    repos, evidence = await _search_topic_repositories(
        Settings(),
        "React",
        token=None,
        limit=3,
    )
    assert [row["full_name"] for row in repos] == ["example/react"]
    assert calls == ["React org:react", "React"]
    assert "q=React" in evidence
    assert "org%3A" not in evidence


@pytest.mark.asyncio
async def test_repository_metadata_emits_release_candidate_without_gold() -> None:
    repo = {
        "full_name": "python/cpython",
        "html_url": "https://github.com/python/cpython",
        "homepage": None,
        "fork": False,
        "archived": False,
    }
    candidates = await _candidates_from_repository(
        Settings(),
        topic="Python",
        concept_id=resolve_concept_id("Python"),
        repository=repo,
        search_evidence_reference="https://api.github.com/search/repositories?q=Python+org%3Apython",
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.url == "https://github.com/python/cpython/releases"
    assert candidate.family == SourceKind.GITHUB_RELEASE.value
    assert candidate.provenance == DiscoveryProvenance.REPOSITORY_METADATA.value
    assert candidate.concept_ids == [resolve_concept_id("Python")]
    assert candidate.observed_via == "github_repository_search"


@pytest.mark.asyncio
async def test_collection_deduplicates_only_identical_candidate_identity(monkeypatch) -> None:
    topic_input = SourceDiscoveryTopicInput(
        artifact_version="source-discovery-topic-input-v0.1",
        topics=["React"],
    )
    repo = {"full_name": "react/react", "fork": False, "archived": False}
    monkeypatch.setattr(
        collector,
        "_search_topic_repositories",
        AsyncMock(return_value=((repo, repo), "https://api.github.com/search/repositories?q=React")),
    )
    artifact = await collector.collect_github_independent_candidates(
        Settings(),
        topic_input,
        repositories_per_topic=2,
    )
    release_urls = [item.url for item in artifact.items if item.family == "github_release"]
    assert release_urls == ["https://github.com/react/react/releases"]
    assert artifact.gold_read is False
