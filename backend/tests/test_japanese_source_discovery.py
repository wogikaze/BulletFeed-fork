from __future__ import annotations

from app.config import get_settings
from app.database import Database
from app.db.topic_catalog import install_topic_catalog
from app.services.source_catalog import SourceKind
from app.services.source_discovery import (
    discover_sources_for_topics,
    list_source_recommendations_for_user,
    record_source_recommendation_decision,
)
from app.services.source_registry import AuthorityStatus, SourceRegistry, canonicalize_url


def _by_url(topic: str):
    result = discover_sources_for_topics(
        (topic,),
        SourceRegistry(seed_mvp=False),
        persist_registry=False,
        limit=80,
    )
    return {item.canonical_url: item for item in result.items}


def test_rust_discovers_zenn_and_qiita_without_claiming_publisher_authority() -> None:
    items = _by_url("Rust")
    zenn = items[canonicalize_url("https://zenn.dev/topics/rust/feed")]
    qiita = items[canonicalize_url("https://qiita.com/tags/rust/feed.atom")]

    for item in (zenn, qiita):
        assert item.family == SourceKind.RSS_ATOM.value
        assert item.actionability == "subscribe"
        assert item.discovery_only is False
        assert item.verification_status == "verified"
        assert item.authority_status == AuthorityStatus.NON_AUTHORITATIVE.value
        assert item.authority_confidence == 0.42
        assert "publisher authority is not assumed" in item.explanation

    official = items[canonicalize_url("https://blog.rust-lang.org/feed.xml")]
    assert official.authority_status == AuthorityStatus.AUTHORITATIVE.value
    assert official.score > zenn.score
    assert official.score > qiita.score


def test_rust_discovers_broad_japanese_web_and_company_blog_feeds() -> None:
    items = _by_url("Rust")
    expected = {
        canonicalize_url("https://b.hatena.ne.jp/entrylist/it.rss"),
        canonicalize_url("https://b.hatena.ne.jp/hotentry/it.rss"),
        canonicalize_url("https://yamadashy.github.io/tech-blog-rss-feed/feeds/rss.xml"),
    }
    assert expected <= set(items)
    for url in expected:
        item = items[url]
        assert item.family == SourceKind.RSS_ATOM.value
        assert item.actionability == "subscribe"
        assert item.verification_status == "verified"
        assert item.authority_status == AuthorityStatus.NON_AUTHORITATIVE.value
        assert item.authority_confidence == 0.42
        assert "publisher authority is not assumed" in item.explanation


def test_react_discovers_verified_japanese_engineering_blogs_as_secondary_sources() -> None:
    items = _by_url("React")
    expected = {
        canonicalize_url("https://techblog.lycorp.co.jp/ja/feed/index.xml"),
        canonicalize_url("https://engineering.mercari.com/blog/feed.xml"),
        canonicalize_url("https://developers.freee.co.jp/feed"),
        canonicalize_url("https://engineering.dena.com/blog/index.xml"),
        canonicalize_url("https://techblog.zozo.com/feed"),
    }
    assert expected <= set(items)
    for url in expected:
        item = items[url]
        assert item.family == SourceKind.RSS_ATOM.value
        assert item.actionability == "subscribe"
        assert item.verification_status == "verified"
        assert item.authority_status == AuthorityStatus.UNKNOWN.value
        assert item.authority_confidence == 0.64
        assert "authority is evaluated independently" in item.explanation


def test_react_first_rss_candidate_stays_activatable_without_japanese_allowlist() -> None:
    result = discover_sources_for_topics(
        ("React",),
        SourceRegistry(seed_mvp=False),
        persist_registry=False,
        limit=80,
    )
    first_rss = next(item for item in result.items if item.family == SourceKind.RSS_ATOM.value)
    assert first_rss.canonical_url == canonicalize_url("https://react.dev/blog/rss.xml")


def test_short_react_page_does_not_pad_with_japanese_catalog() -> None:
    result = discover_sources_for_topics(
        ("React",),
        SourceRegistry(seed_mvp=False),
        persist_registry=False,
        limit=6,
    )
    urls = {item.canonical_url for item in result.items}
    assert canonicalize_url("https://react.dev/blog/rss.xml") in urls
    assert not any("zenn.dev" in url or "qiita.com" in url for url in urls)
    assert not any("b.hatena.ne.jp" in url or "yamadashy.github.io" in url for url in urls)


def test_unmapped_topic_does_not_synthesize_arbitrary_platform_feed_urls() -> None:
    items = _by_url("LLVM Scalar Evolution")
    assert not any("zenn.dev/topics/" in url for url in items)
    assert not any("qiita.com/tags/" in url for url in items)


def test_approving_community_feed_does_not_register_it_as_authoritative(
    database: Database,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BULLETFEED_RSS_ALLOWED_HOSTS", "zenn.dev,blog.rust-lang.org")
    get_settings.cache_clear()
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
    items = list_source_recommendations_for_user(database, "user_a", limit=80).items
    zenn = next(item for item in items if "zenn.dev/topics/rust/feed" in item.canonical_url)
    assert zenn.authority_status == AuthorityStatus.NON_AUTHORITATIVE.value
    record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=zenn.candidate_id,
        decision="approved",
    )
    endpoint = SourceRegistry(database).find_duplicate_endpoint(
        zenn.canonical_url,
        family=SourceKind.RSS_ATOM,
    )
    assert endpoint is not None
    assert endpoint.authority_status == AuthorityStatus.NON_AUTHORITATIVE.value
    assert endpoint.verification_status == "verified"


def test_approving_hatena_index_feed_does_not_register_it_as_authoritative(
    database: Database,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BULLETFEED_RSS_ALLOWED_HOSTS", "b.hatena.ne.jp,blog.rust-lang.org")
    get_settings.cache_clear()
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
    items = list_source_recommendations_for_user(database, "user_a", limit=80).items
    hatena = next(item for item in items if "b.hatena.ne.jp/entrylist/it.rss" in item.canonical_url)
    assert hatena.authority_status == AuthorityStatus.NON_AUTHORITATIVE.value
    record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=hatena.candidate_id,
        decision="approved",
    )
    endpoint = SourceRegistry(database).find_duplicate_endpoint(
        hatena.canonical_url,
        family=SourceKind.RSS_ATOM,
    )
    assert endpoint is not None
    assert endpoint.authority_status == AuthorityStatus.NON_AUTHORITATIVE.value
    assert endpoint.verification_status == "verified"
