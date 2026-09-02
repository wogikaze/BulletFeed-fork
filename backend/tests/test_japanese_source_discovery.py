from __future__ import annotations

from app.services.source_catalog import SourceKind
from app.services.source_discovery import discover_sources_for_topics
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


def test_unmapped_topic_does_not_synthesize_arbitrary_platform_feed_urls() -> None:
    items = _by_url("LLVM Scalar Evolution")
    assert not any("zenn.dev/topics/" in url for url in items)
    assert not any("qiita.com/tags/" in url for url in items)
