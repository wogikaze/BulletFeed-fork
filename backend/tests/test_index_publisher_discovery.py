from __future__ import annotations

from pathlib import Path

import pytest

from app.database import Database
from app.services.index_publisher_discovery import (
    original_article_hosts,
    publisher_feed_hints_from_index_preview,
)
from app.services.japanese_source_catalog import INDEX_DERIVED_SLUG_PREFIX
from app.services.rss_pipeline import ingest_feed_events
from app.services.source_discovery_runtime import load_runtime_discovery_hints
from app.services.source_registry import AuthorityStatus, SourceRegistry, VerificationStatus
from app.stores.discovery_store import DiscoveryStore

INDEX = "https://b.hatena.ne.jp/entrylist/it.rss"


def test_index_preview_keeps_original_hosts_and_skips_index_and_community() -> None:
    hosts = original_article_hosts(
        (
            {"link": "https://engineering.example.com/posts/one"},
            {"link": "https://b.hatena.ne.jp/entry/s/engineering.example.com/posts/one"},
            {"link": "https://zenn.dev/team/articles/one"},
            {"link": "https://blog.company.example.jp/entry"},
        ),
        index_url=INDEX,
    )
    assert hosts == ("engineering.example.com", "blog.company.example.jp")


def test_hatena_entry_permalink_unwraps_to_original_host() -> None:
    from app.services.index_publisher_discovery import unwrap_index_article_url

    assert (
        unwrap_index_article_url("https://b.hatena.ne.jp/entry/s/engineering.example.com/posts/one")
        == "https://engineering.example.com/posts/one"
    )
    hosts = original_article_hosts(
        ({"link": "https://b.hatena.ne.jp/entry/s/news.example.com/tech/rust"},),
        index_url=INDEX,
    )
    assert hosts == ("news.example.com",)


def test_index_preview_emits_unconfirmed_publisher_feed_probes() -> None:
    hints = publisher_feed_hints_from_index_preview(
        ({"link": "https://engineering.example.com/posts/one", "title": "One"},),
        index_url=INDEX,
        concept_ids=("rust",),
    )
    assert len(hints) == 1
    hint = hints[0]
    assert hint.url.startswith("https://engineering.example.com/")
    assert hint.publisher_slug.startswith(INDEX_DERIVED_SLUG_PREFIX)
    assert hint.family.value == "rss_atom"
    assert "not publisher authority" in hint.why


def test_non_index_preview_does_not_emit_publisher_probes() -> None:
    hints = publisher_feed_hints_from_index_preview(
        ({"link": "https://engineering.example.com/posts/one"},),
        index_url="https://blog.rust-lang.org/feed.xml",
    )
    assert hints == ()


def test_ingesting_index_preview_persists_unconfirmed_publisher_hints(tmp_path: Path) -> None:
    database = Database(tmp_path / "index-hints.db")
    database.initialize()
    preview = {
        "title": "はてなブックマーク",
        "source_url": INDEX,
        "items": [
            {
                "title": "Example corp post",
                "link": "https://engineering.example.com/posts/one",
                "published": "2026-09-01T00:00:00Z",
                "summary": "Short teaser.",
            }
        ],
    }
    first = ingest_feed_events(
        database,
        preview=preview,
        retrieved_at="2026-09-01T00:01:00Z",
    )
    second = ingest_feed_events(
        database,
        preview=preview,
        retrieved_at="2026-09-01T00:02:00Z",
    )
    assert first.event_ids == second.event_ids == ()
    assert first.claim_ids == second.claim_ids == ()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == 0
    hints = load_runtime_discovery_hints(database)
    assert any(
        item.publisher_slug.startswith(INDEX_DERIVED_SLUG_PREFIX)
        and item.url.startswith("https://engineering.example.com/")
        for item in hints
    )
    stored = [
        item
        for item in DiscoveryStore(database).list_all()
        if str(item.metadata.get("publisher_slug", "")).startswith(INDEX_DERIVED_SLUG_PREFIX)
    ]
    assert len(stored) == 1
    assert stored[0].first_seen_at == "2026-09-01T00:01:00Z"
    assert stored[0].last_seen_at == "2026-09-01T00:02:00Z"


def test_index_discovery_write_failure_does_not_fail_ingest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = Database(tmp_path / "index-hints-failure.db")
    database.initialize()

    def fail_persist(*_args, **_kwargs):
        raise OSError("discovery store unavailable")

    monkeypatch.setattr(
        "app.services.source_discovery_runtime.persist_runtime_discovery_hints",
        fail_persist,
    )
    result = ingest_feed_events(
        database,
        preview={
            "title": "はてなブックマーク",
            "source_url": INDEX,
            "items": [{"link": "https://engineering.example.com/posts/one"}],
        },
        retrieved_at="2026-09-01T00:01:00Z",
    )

    assert result.event_ids == ()
    assert result.claim_ids == ()


def test_index_derived_probe_stays_unverified_and_not_authoritative() -> None:
    from app.services.source_discovery import discover_sources_for_topics
    from app.services.source_registry import SourceRegistry

    hints = publisher_feed_hints_from_index_preview(
        ({"link": "https://engineering.example.com/posts/one"},),
        index_url=INDEX,
        concept_ids=("rust",),
    )
    result = discover_sources_for_topics(
        ("Rust",),
        SourceRegistry(seed_mvp=False),
        persist_registry=False,
        limit=80,
        hints=hints,
    )
    probe = next(item for item in result.items if item.publisher_slug.startswith(INDEX_DERIVED_SLUG_PREFIX))
    assert probe.authority_status == AuthorityStatus.UNKNOWN.value
    assert probe.verification_status == "unverified"


def test_existing_index_endpoint_is_reclassified_from_authoritative(tmp_path: Path) -> None:
    from app.services.source_discovery import discover_sources_for_topics

    database = Database(tmp_path / "registry-reconcile.db")
    database.initialize()
    registry = SourceRegistry(database, seed_mvp=False)
    registry.register_endpoint(
        url=INDEX,
        family="rss_atom",
        verification_status=VerificationStatus.VERIFIED,
        authority_status=AuthorityStatus.AUTHORITATIVE,
    )

    result = discover_sources_for_topics(
        ("Rust",),
        registry,
        persist_registry=True,
        limit=80,
    )
    candidate = next(item for item in result.items if item.canonical_url == INDEX)
    assert candidate.verification_status == VerificationStatus.VERIFIED.value
    assert candidate.authority_status == AuthorityStatus.NON_AUTHORITATIVE.value
    endpoint = SourceRegistry(database, seed_mvp=False).find_duplicate_endpoint(
        INDEX,
        family="rss_atom",
    )
    assert endpoint is not None
    assert endpoint.authority_status == AuthorityStatus.NON_AUTHORITATIVE.value


def test_approving_index_derived_probe_does_not_register_it_as_authoritative(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.config import get_settings
    from app.db.topic_catalog import install_topic_catalog
    from app.services.source_discovery import (
        list_source_recommendations_for_user,
        record_source_recommendation_decision,
    )
    from app.services.source_registry import SourceRegistry

    monkeypatch.setenv(
        "BULLETFEED_RSS_ALLOWED_HOSTS",
        "b.hatena.ne.jp,engineering.example.com,blog.rust-lang.org",
    )
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.source_subscriptions.validate_feed_url",
        lambda url, _hosts, **_kwargs: url,
    )
    database = Database(tmp_path / "index-approve.db")
    database.initialize()
    install_topic_catalog(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", ("user_a",))
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES (?, ?, ?, 'technology', ?, ?, 1)
            """,
            ("user_a-topic-0", "user_a", "Rust", "high", 0),
        )
    ingest_feed_events(
        database,
        preview={
            "title": "はてなブックマーク",
            "source_url": INDEX,
            "items": [
                {
                    "title": "Example corp post",
                    "link": "https://engineering.example.com/posts/one",
                    "published": "2026-09-01T00:00:00Z",
                    "summary": "Short teaser.",
                }
            ],
        },
        retrieved_at="2026-09-01T00:01:00Z",
    )
    items = list_source_recommendations_for_user(database, "user_a", limit=80).items
    probe = next(item for item in items if item.publisher_slug.startswith(INDEX_DERIVED_SLUG_PREFIX))
    with pytest.raises(ValueError, match="confirmed"):
        record_source_recommendation_decision(
            database,
            user_id="user_a",
            candidate_id=probe.candidate_id,
            decision="approved",
        )
    endpoint = SourceRegistry(database).find_duplicate_endpoint(probe.canonical_url, family="rss_atom")
    assert endpoint is None
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_sync_subscription_users").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM source_discovery_decisions").fetchone()[0] == 0


def test_homepage_url_from_probe_strips_well_known_path() -> None:
    from app.services.index_publisher_discovery import homepage_url_from_probe

    assert homepage_url_from_probe("https://engineering.example.com/feed") == "https://engineering.example.com/"
    assert homepage_url_from_probe("https://www.news.example.jp/rss.xml") == "https://news.example.jp/"


@pytest.mark.asyncio
async def test_confirm_index_publisher_feed_prefers_html_alternate(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.config import Settings
    from app.services.index_publisher_discovery import confirm_index_publisher_feed

    async def fake_discover(settings, url, **kwargs):
        assert kwargs.get("persist_registry") is False
        assert kwargs.get("probe_well_known") is False
        if url == "https://engineering.example.com/":
            return SimpleNamespace(
                items=(
                    SimpleNamespace(
                        family="rss_atom",
                        discovery_method="html_link_alternate",
                        canonical_url="https://engineering.example.com/blog/feed.xml",
                    ),
                )
            )
        assert url == "https://engineering.example.com/blog/feed.xml"
        return SimpleNamespace(
            items=(
                SimpleNamespace(
                    family="rss_atom",
                    discovery_method="direct_feed_url",
                    canonical_url=url,
                ),
            )
        )

    monkeypatch.setattr(
        "app.services.source_feed_discover.discover_feeds_from_site_url",
        fake_discover,
    )
    confirmed = await confirm_index_publisher_feed(
        Settings(),
        probe_url="https://engineering.example.com/feed",
    )
    assert confirmed == "https://engineering.example.com/blog/feed.xml"


@pytest.mark.asyncio
async def test_confirm_index_publisher_feed_rejects_probe_when_html_fails(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.config import Settings
    from app.services.index_publisher_discovery import confirm_index_publisher_feed

    async def fake_discover(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Web fetching is disabled")

    monkeypatch.setattr(
        "app.services.source_feed_discover.discover_feeds_from_site_url",
        fake_discover,
    )
    probe = "https://engineering.example.com/feed"
    assert await confirm_index_publisher_feed(Settings(), probe_url=probe) is None


def test_approving_index_derived_probe_subscribes_html_confirmed_feed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.config import get_settings
    from app.db.topic_catalog import install_topic_catalog
    from app.services.source_discovery import (
        list_source_recommendations_for_user,
        record_source_recommendation_decision,
    )
    from app.services.source_registry import SourceRegistry, VerificationStatus, canonicalize_url

    monkeypatch.setenv(
        "BULLETFEED_RSS_ALLOWED_HOSTS",
        "b.hatena.ne.jp,engineering.example.com,blog.rust-lang.org",
    )
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.source_subscriptions.validate_feed_url",
        lambda url, _hosts, **_kwargs: url,
    )
    database = Database(tmp_path / "index-confirm.db")
    database.initialize()
    install_topic_catalog(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", ("user_a",))
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES (?, ?, ?, 'technology', ?, ?, 1)
            """,
            ("user_a-topic-0", "user_a", "Rust", "high", 0),
        )
    ingest_feed_events(
        database,
        preview={
            "title": "はてなブックマーク",
            "source_url": INDEX,
            "items": [
                {
                    "title": "Example corp post",
                    "link": "https://engineering.example.com/posts/one",
                    "published": "2026-09-01T00:00:00Z",
                    "summary": "Short teaser.",
                }
            ],
        },
        retrieved_at="2026-09-01T00:01:00Z",
    )
    items = list_source_recommendations_for_user(database, "user_a", limit=80).items
    probe = next(item for item in items if item.publisher_slug.startswith(INDEX_DERIVED_SLUG_PREFIX))
    confirmed = "https://engineering.example.com/blog/feed.xml"
    record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=probe.candidate_id,
        decision="approved",
        subscribe_url=confirmed,
        verification_status=VerificationStatus.VERIFIED.value,
    )
    endpoint = SourceRegistry(database).find_duplicate_endpoint(confirmed, family="rss_atom")
    assert endpoint is not None
    assert endpoint.authority_status == AuthorityStatus.UNKNOWN.value
    assert endpoint.verification_status == VerificationStatus.VERIFIED.value
    assert endpoint.verification_method == "index_publisher_confirmation"
    assert endpoint.verification_reference == confirmed
    assert endpoint.verified_at
    with database.connect() as connection:
        keys = [
            row["source_key"]
            for row in connection.execute(
                "SELECT source_key FROM source_sync_subscriptions"
            ).fetchall()
        ]
    assert canonicalize_url(confirmed) in keys
