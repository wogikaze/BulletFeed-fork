from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Database
from app.db.topic_catalog import install_topic_catalog
from app.services.source_actionability import (
    SOURCE_FAMILY_ACTIONS,
    missing_source_family_actions,
    resolve_source_actionability,
)
from app.services.source_catalog import SourceKind
from app.services.source_discovery import (
    DiscoveryHint,
    list_source_recommendations_for_user,
    record_source_recommendation_decision,
)
from app.services.source_discovery_runtime import persist_runtime_discovery_hints
from app.services.source_discovery_seeds import DiscoveryProvenance


def _seed_user(connection, user_id: str, *, topics: tuple[tuple[str, str], ...]) -> None:
    connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", (user_id,))
    for index, (name, priority) in enumerate(topics):
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES (?, ?, ?, 'technology', ?, ?, 1)
            """,
            (f"{user_id}-topic-{index}", user_id, name, priority, index),
        )


_COUNT_SQL = {
    "source_sync_subscriptions": "SELECT COUNT(*) AS count FROM source_sync_subscriptions",
    "source_sync_jobs": "SELECT COUNT(*) AS count FROM source_sync_jobs",
}


def _count(database: Database, table: str) -> int:
    with database.connect() as connection:
        return int(connection.execute(_COUNT_SQL[table]).fetchone()["count"])


def test_every_source_kind_has_explicit_actionability() -> None:
    assert missing_source_family_actions() == ()
    assert set(SOURCE_FAMILY_ACTIONS) == {kind.value for kind in SourceKind}


def test_external_index_stays_discovery_only_even_for_watchable_hosts() -> None:
    assert (
        resolve_source_actionability(
            family=SourceKind.RSS_ATOM.value,
            discovery_provenance=DiscoveryProvenance.EXTERNAL_INDEX.value,
        )
        == "discovery_only"
    )
    assert (
        resolve_source_actionability(family=SourceKind.HACKER_NEWS_DISCOVERY.value)
        == "discovery_only"
    )
    assert resolve_source_actionability(family=SourceKind.GENERIC_WEB.value) == "subscribe"
    assert resolve_source_actionability(family=SourceKind.GITHUB_RELEASE.value) == "select_repository"
    assert resolve_source_actionability(family=SourceKind.GITHUB_ADVISORY.value) == "unsupported"
    assert resolve_source_actionability(family=SourceKind.OSV.value) == "unsupported"


def test_subscribe_families_create_watch_jobs(database, monkeypatch) -> None:
    monkeypatch.setenv("BULLETFEED_RSS_ALLOWED_HOSTS", "react.dev")
    get_settings.cache_clear()
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "user_a", topics=(("React", "high"),))
    items = list_source_recommendations_for_user(database, "user_a").items
    assert {item.actionability for item in items}
    rss = next(item for item in items if item.family == SourceKind.RSS_ATOM.value)
    release = next(item for item in items if item.family == SourceKind.GITHUB_RELEASE.value)
    assert rss.actionability == "subscribe"
    assert release.actionability == "select_repository"
    record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=rss.candidate_id,
        decision="approved",
    )
    record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=release.candidate_id,
        decision="approved",
    )
    assert _count(database, "source_sync_subscriptions") == 1
    assert _count(database, "source_sync_jobs") == 1


def test_generic_web_subscribe_creates_watch_job(database, monkeypatch) -> None:
    monkeypatch.setenv("BULLETFEED_WEB_ALLOWED_HOSTS", "bun.sh")
    get_settings.cache_clear()
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "user_bun", topics=(("Bun", "high"),))
    items = list_source_recommendations_for_user(database, "user_bun").items
    web = next(item for item in items if item.family == SourceKind.GENERIC_WEB.value)
    assert web.actionability == "subscribe"
    record_source_recommendation_decision(
        database,
        user_id="user_bun",
        candidate_id=web.candidate_id,
        decision="approved",
    )
    assert _count(database, "source_sync_subscriptions") == 1
    assert _count(database, "source_sync_jobs") == 1


def test_unsupported_family_cannot_be_approved(database) -> None:
    install_topic_catalog(database)
    persist_runtime_discovery_hints(
        database,
        (
            DiscoveryHint(
                url="https://github.com/advisories/GHSA-test-react",
                provenance=DiscoveryProvenance.REPOSITORY_METADATA.value,
                family=SourceKind.GITHUB_ADVISORY,
                concept_ids=("react",),
                title="React advisory",
                publisher_slug="github",
                publisher_name="GitHub",
                homepage_url="https://github.com/advisories",
                why="Advisory index is not a user-watch family yet",
                display_name="React advisory",
            ),
        ),
    )
    with database.connect() as connection:
        _seed_user(connection, "user_a", topics=(("React", "high"),))
    items = list_source_recommendations_for_user(database, "user_a").items
    blocked = next(item for item in items if item.actionability == "unsupported")
    with pytest.raises(ValueError, match="cannot be approved"):
        record_source_recommendation_decision(
            database,
            user_id="user_a",
            candidate_id=blocked.candidate_id,
            decision="approved",
        )
    assert _count(database, "source_sync_subscriptions") == 0


def test_api_exposes_actionability_and_rejects_hn_approve(
    client: TestClient,
    auth_headers,
) -> None:
    created = client.post(
        "/v1/me/topics",
        headers=auth_headers,
        json={"name": "React", "type": "technology"},
    )
    assert created.status_code == 201
    listed = client.get("/v1/me/source-recommendations", headers=auth_headers)
    assert listed.status_code == 200
    assert all("actionability" in item for item in listed.json()["items"])
    hn = next(
        (
            item
            for item in listed.json()["items"]
            if item["actionability"] == "discovery_only"
        ),
        None,
    )
    if hn is not None:
        denied = client.post(
            f"/v1/me/source-recommendations/{hn['id']}",
            headers=auth_headers,
            json={"decision": "approved"},
        )
        assert denied.status_code == 422
