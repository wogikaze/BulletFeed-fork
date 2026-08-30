from __future__ import annotations

from pathlib import Path

from app.database import Database
from app.db.topic_catalog import install_topic_catalog
from app.evaluation.source_discovery_gold import (
    evaluate_source_discovery,
    load_source_discovery_gold,
)
from app.observability import counters, reset
from app.services.sitemap_discovery import record_sitemap_candidates
from app.services.source_catalog import SourceKind
from app.services.source_discovery import (
    DiscoveryHint,
    discover_sources_for_topics,
    list_source_recommendations_for_user,
)
from app.services.source_discovery_runtime import (
    default_runtime_collector,
    load_runtime_discovery_hints,
    persist_runtime_discovery_hints,
    refresh_runtime_discovery_for_topics,
)
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_registry import SourceRegistry, canonicalize_url
from app.stores.discovery_store import DiscoveryStore

_GOLD = Path(__file__).parent / "gold" / "source_discovery" / "v01" / "cases.json"


def _seed_user(connection, user_id: str, *, topics: tuple[tuple[str, str], ...] = ()) -> None:
    connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", (user_id,))
    for index, (name, priority) in enumerate(topics):
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES (?, ?, ?, 'technology', ?, ?, 1)
            """,
            (f"{user_id}-topic-{index}", user_id, name, priority, index),
        )


def test_no_seed_topic_finds_official_runtime_candidates(tmp_path) -> None:
    database = Database(tmp_path / "runtime.db")
    database.initialize()
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "user_bun", topics=(("Bun", "high"),))

    result = list_source_recommendations_for_user(database, "user_bun")
    urls = {item.canonical_url for item in result.items}
    assert canonicalize_url("https://bun.sh/rss.xml") in urls
    assert canonicalize_url("https://bun.sh/sitemap.xml") in urls
    assert canonicalize_url("https://status.bun.sh/api/v2/summary.json") in urls
    assert result.runtime_hint_count >= 3
    assert result.seed_fallback_used is False
    feed = next(item for item in result.items if item.canonical_url.endswith("/rss.xml"))
    assert feed.discovery_provenance == DiscoveryProvenance.WEBSITE_FEED
    assert feed.evidence_eligible is False
    persisted = DiscoveryStore(database).list_all()
    assert any(row.target_url.endswith("/rss.xml") for row in persisted)
    registry = SourceRegistry(database)
    assert registry.find_duplicate_endpoint("https://bun.sh/rss.xml", family=SourceKind.RSS_ATOM) is None


def test_hn_and_external_index_never_persist_as_truth(tmp_path) -> None:
    database = Database(tmp_path / "hn-runtime.db")
    database.initialize()
    persist_runtime_discovery_hints(
        database,
        (
            DiscoveryHint(
                url="https://news.ycombinator.com/item?id=1",
                provenance=DiscoveryProvenance.EXTERNAL_INDEX.value,
                family=SourceKind.HACKER_NEWS_DISCOVERY,
                concept_ids=("bun",),
                title="HN thread",
                why="Suggested by Hacker News",
            ),
        ),
    )
    assert load_runtime_discovery_hints(database) == ()
    assert DiscoveryStore(database).list_all() == []


def test_persisted_sitemap_candidates_reenter_recommendations(tmp_path) -> None:
    database = Database(tmp_path / "sitemap.db")
    database.initialize()
    install_topic_catalog(database)
    record_sitemap_candidates(
        database,
        sitemap_url="https://bun.sh/sitemap.xml",
        xml_bytes=b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://bun.sh/blog/bun-v1</loc></url>
</urlset>
""",
        seen_at="2026-08-30T00:00:00Z",
    )
    persist_runtime_discovery_hints(database, default_runtime_collector(("Bun",)))
    with database.connect() as connection:
        _seed_user(connection, "user_bun", topics=(("Bun", "high"),))
    result = list_source_recommendations_for_user(database, "user_bun")
    assert result.runtime_hint_count >= 4
    assert canonicalize_url("https://bun.sh/rss.xml") in {item.canonical_url for item in result.items}


def test_network_failure_falls_back_to_seeds_and_is_measured(tmp_path) -> None:
    database = Database(tmp_path / "fallback.db")
    database.initialize()
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "user_react", topics=(("React", "high"),))
    reset()

    def boom(_topics):
        raise TimeoutError("collector offline")

    refresh = refresh_runtime_discovery_for_topics(
        database,
        ("react",),
        collector=boom,
    )
    assert refresh.seed_fallback_used is True
    assert counters()["runtime_discovery_fallback_seed"] == 1

    result = list_source_recommendations_for_user(database, "user_react")
    urls = " ".join(item.canonical_url for item in result.items)
    assert "react.dev" in urls or "facebook/react" in urls


def test_seed_vs_no_seed_recall_is_segmented() -> None:
    gold = load_source_discovery_gold(_GOLD)
    report = evaluate_source_discovery(gold, registry=SourceRegistry())
    assert report.seed_mean_recall >= 0.45
    no_seed = discover_sources_for_topics(
        ("Bun",),
        SourceRegistry(),
        include_curated_seeds=False,
        hints=default_runtime_collector(("Bun",)),
    )
    urls = {item.canonical_url for item in no_seed.items}
    assert canonicalize_url("https://bun.sh/rss.xml") in urls
    seed_only = discover_sources_for_topics(
        ("Bun",),
        SourceRegistry(),
        include_curated_seeds=True,
    )
    assert canonicalize_url("https://bun.sh/rss.xml") not in {item.canonical_url for item in seed_only.items}
