from __future__ import annotations

from pathlib import Path

from app.database import Database
from app.db.topic_catalog import install_topic_catalog
from app.evaluation.source_discovery_gold import evaluate_source_discovery, load_source_discovery_gold
from app.observability import counters, reset
from app.services.sitemap_discovery import record_sitemap_candidates
from app.services.source_catalog import SourceKind
from app.services.source_discovery import (
    discover_sources_for_topics,
    list_source_recommendations_for_user,
)
from app.services.source_discovery_runtime import (
    default_runtime_collector,
    persist_runtime_discovery_hints,
    refresh_runtime_discovery_for_topics,
)
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_registry import SourceRegistry, canonicalize_url
from app.stores.discovery_store import DiscoveryStore

_GOLD = Path(__file__).parent / "gold" / "source_discovery" / "v01" / "cases.json"


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


def test_topic_without_curated_seed_finds_official_runtime_candidates() -> None:
    hints = default_runtime_collector(("Bun",))
    result = discover_sources_for_topics(
        ("Bun",),
        SourceRegistry(seed_mvp=False),
        include_curated_seeds=False,
        hints=hints,
    )
    urls = {item.canonical_url for item in result.items}
    assert canonicalize_url("https://bun.sh/rss.xml") in urls
    assert canonicalize_url("https://bun.sh/sitemap.xml") in urls
    assert canonicalize_url("https://status.bun.sh/api/v2/summary.json") in urls
    provenances = {item.discovery_provenance for item in result.items}
    assert DiscoveryProvenance.WEBSITE_FEED.value in provenances
    assert DiscoveryProvenance.SITEMAP_LINK.value in provenances
    assert DiscoveryProvenance.STATUSPAGE_LINK.value in provenances
    assert DiscoveryProvenance.PACKAGE_HOMEPAGE.value in provenances
    assert all(item.evidence_eligible is False for item in result.items)
    assert all(
        item.discovery_only is True
        for item in result.items
        if item.discovery_provenance == DiscoveryProvenance.EXTERNAL_INDEX.value
    )


def test_runtime_hints_persist_provenance_and_registry(tmp_path: Path) -> None:
    database = Database(tmp_path / "runtime.db")
    database.initialize()
    hints = default_runtime_collector(("svelte",))
    persisted = persist_runtime_discovery_hints(database, hints)
    assert persisted == len(hints)
    store = DiscoveryStore(database)
    rows = store.list_all()
    assert {row.discovery_method for row in rows} >= {
        DiscoveryProvenance.WEBSITE_FEED.value,
        DiscoveryProvenance.SITEMAP_LINK.value,
    }
    assert all(row.metadata.get("concept_ids") == ["svelte"] for row in rows)
    registry = SourceRegistry(database)
    feed = registry.find_duplicate_endpoint(
        "https://svelte.dev/blog/rss.xml",
        family=SourceKind.RSS_ATOM,
    )
    assert feed is not None


def test_persisted_sitemap_candidates_reenter_recommendations(tmp_path: Path) -> None:
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
    assert result.seed_fallback_used is False
    urls = {item.canonical_url for item in result.items}
    assert canonicalize_url("https://bun.sh/rss.xml") in urls
    assert any("bun.sh" in item.canonical_url for item in result.items)


def test_collector_failure_falls_back_to_seeds_and_is_measured(tmp_path: Path) -> None:
    reset()
    database = Database(tmp_path / "fallback.db")
    database.initialize()
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "user_react", topics=(("React", "high"),))

    def boom(_topics):
        raise TimeoutError("upstream discovery unavailable")

    refresh = refresh_runtime_discovery_for_topics(
        database,
        ("react",),
        collector=boom,
    )
    assert refresh.seed_fallback_used is True
    assert refresh.persisted == 0
    assert counters().get("runtime_discovery_fallback_seed", 0) >= 1
    result = list_source_recommendations_for_user(database, "user_react")
    urls = {item.canonical_url for item in result.items}
    assert canonicalize_url("https://github.com/facebook/react/releases") in urls
    assert all(
        item.discovery_only is True
        for item in result.items
        if item.discovery_provenance == DiscoveryProvenance.EXTERNAL_INDEX.value
    )


def test_seed_versus_no_seed_recall_is_segmented() -> None:
    gold = load_source_discovery_gold(_GOLD)
    report = evaluate_source_discovery(gold, registry=SourceRegistry())
    assert report.seed_mean_recall >= 0.45
    assert report.no_seed_mean_recall >= 0.0
    bun = discover_sources_for_topics(
        ("Bun",),
        SourceRegistry(seed_mvp=False),
        include_curated_seeds=False,
        hints=default_runtime_collector(("Bun",)),
    )
    seed_only = discover_sources_for_topics(
        ("Bun",),
        SourceRegistry(seed_mvp=False),
        include_curated_seeds=True,
    )
    assert bun.items
    assert not any("bun.sh" in item.canonical_url for item in seed_only.items)
