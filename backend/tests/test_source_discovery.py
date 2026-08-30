from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Database
from app.db.topic_catalog import install_topic_catalog
from app.evaluation.source_discovery_gold import (
    evaluate_source_discovery,
    load_source_discovery_gold,
)
from app.services.source_catalog import SourceKind, source_allows_claim_evidence
from app.services.source_discovery import (
    SOURCE_DISCOVERY_VERSION,
    DiscoveryHint,
    discover_sources,
    discover_sources_for_topics,
    discovery_signal_allows_claim_evidence,
    list_source_recommendations_for_user,
    record_source_recommendation_decision,
    source_candidate_allows_claim_evidence,
)
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.services.source_registry import SourceRegistry, canonicalize_url
from app.services.user_interest import InterestSources, rebuild_user_interest, signals_from_sources
from app.stores.claim_ledger_store import ClaimLedgerStore

_GOLD = Path(__file__).parent / "gold" / "source_discovery" / "v01" / "cases.json"


def _state(
    user_id: str,
    *,
    topics: tuple[tuple[str, str], ...] = (),
    repositories: tuple[tuple[str, str], ...] = (),
    interests: tuple[str, ...] = (),
):
    return rebuild_user_interest(
        user_id,
        signals_from_sources(
            InterestSources(
                topics=topics,
                repositories=repositories,
                profile_interests=interests,
            )
        ),
    )


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


_COUNT_TABLES = {
    "source_sync_subscriptions": "SELECT COUNT(*) AS count FROM source_sync_subscriptions",
    "source_sync_jobs": "SELECT COUNT(*) AS count FROM source_sync_jobs",
    "observations": "SELECT COUNT(*) AS count FROM observations",
    "state_claims": "SELECT COUNT(*) AS count FROM state_claims",
}


def _count(database: Database, table: str) -> int:
    query = _COUNT_TABLES[table]
    with database.connect() as connection:
        return int(connection.execute(query).fetchone()["count"])


def test_discovery_is_not_evidence_and_hn_stays_discovery_only() -> None:
    state = _state("u_react", topics=(("React", "high"),))
    hn_items = (
        {
            "id": 1,
            "title": "React 19 released",
            "url": "https://react.dev/blog/2026/react-19",
        },
        {
            "id": 2,
            "title": "How to react in an emergency",
            "url": "https://reactor.example/emergency",
        },
    )
    result = discover_sources(
        state,
        SourceRegistry(seed_mvp=True),
        hn_items=hn_items,
    )

    assert result.version == SOURCE_DISCOVERY_VERSION
    assert result.items
    assert all(item.evidence_eligible is False for item in result.items)
    assert all(source_candidate_allows_claim_evidence(item) is False for item in result.items)
    official = [
        item
        for item in result.items
        if "react.dev" in item.canonical_url or "facebook/react" in item.canonical_url
    ]
    assert official
    assert official[0].authority_status == "authoritative"
    assert official[0].score > max(
        (item.score for item in result.items if item.discovery_only),
        default=0.0,
    )
    hn = [item for item in result.items if item.discovery_provenance == DiscoveryProvenance.EXTERNAL_INDEX]
    assert hn
    assert all(item.discovery_only is True for item in hn)
    assert all("Claim evidence" in item.explanation for item in hn)
    assert not any("reactor.example" in item.canonical_url for item in result.items)
    assert discovery_signal_allows_claim_evidence(
        source_type=SourceKind.HACKER_NEWS_DISCOVERY.value,
        discovery_provenance=DiscoveryProvenance.EXTERNAL_INDEX.value,
    ) is False
    assert source_allows_claim_evidence(SourceKind.HACKER_NEWS_DISCOVERY.value) is False


def test_candidate_records_include_why_and_how() -> None:
    result = discover_sources_for_topics(("LLVM Scalar Evolution",), SourceRegistry())
    assert result.items
    item = result.items[0]
    assert item.match_reason
    assert item.discovery_provenance
    assert item.explanation
    assert "Discovered via" in item.explanation
    assert item.family
    assert item.matched_concept_ids
    assert item.authority_confidence > 0


def test_official_verified_sources_outrank_hn_suggestions() -> None:
    state = _state("u_py", topics=(("Python", "high"),))
    result = discover_sources(
        state,
        SourceRegistry(),
        hn_items=(
            {
                "id": 9,
                "title": "Python 3.14 notes",
                "url": "https://hn-mirror.example/python-notes",
            },
        ),
    )
    official = next(item for item in result.items if item.verification_status == "verified")
    hn = next(item for item in result.items if item.discovery_only)
    assert official.score > hn.score
    assert official.authority_confidence > hn.authority_confidence


def test_duplicate_endpoints_canonicalize_through_registry() -> None:
    registry = SourceRegistry(seed_mvp=False)
    state = _state("u_dup", topics=(("React", "high"),))
    result = discover_sources(
        state,
        registry,
        hints=(
            DiscoveryHint(
                url="http://www.react.dev/blog/rss.xml?utm_source=share",
                provenance=DiscoveryProvenance.WEBSITE_FEED.value,
                family=SourceKind.RSS_ATOM,
                concept_ids=("react",),
                display_name="React blog alias",
                why="Website feed discovery",
            ),
        ),
    )
    feeds = [item for item in result.items if item.family == SourceKind.RSS_ATOM.value]
    urls = {item.canonical_url for item in feeds}
    assert canonicalize_url("https://react.dev/blog/rss.xml") in urls
    assert len({item.endpoint_id for item in feeds}) == len(feeds)
    duplicate = registry.find_duplicate_endpoint(
        "https://react.dev/blog/rss.xml/",
        family=SourceKind.RSS_ATOM,
    )
    assert duplicate is not None
    assert any(item.endpoint_id == duplicate.endpoint_id for item in feeds)


def test_hn_suggested_url_cannot_become_claim_evidence(tmp_path: Path) -> None:
    database = Database(tmp_path / "hn.db")
    database.initialize()
    observations = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="hacker_news_discovery",
                source_key="topstories",
                source_observation_id="99",
                payload={"title": "React 19 released", "url": "https://react.dev/blog/2026/react-19"},
                original_url="https://react.dev/blog/2026/react-19",
                published_at="2026-08-20T10:00:00Z",
            ),
        ),
        retrieved_at="2026-08-20T10:01:00Z",
    )
    ledger = ClaimLedgerStore(database)
    with pytest.raises(ValueError, match="not eligible for claim evidence"):
        ledger.ingest(
            observations[0],
            source_event_id="99",
            title="React 19",
            slot="publication_state",
            value="published",
            detail="HN suggested this URL",
            valid_at="2026-08-20T10:00:00Z",
            evidence_text="HN candidate",
        )


def test_approve_ignore_does_not_auto_subscribe(tmp_path: Path) -> None:
    database = Database(tmp_path / "disc.db")
    database.initialize()
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "user_a", topics=(("React", "high"),))
        _seed_user(connection, "user_b", topics=(("Python", "high"),))

    before_subs = _count(database, "source_sync_subscriptions")
    before_jobs = _count(database, "source_sync_jobs")
    alice = list_source_recommendations_for_user(database, "user_a")
    bob = list_source_recommendations_for_user(database, "user_b")
    assert alice.items
    assert bob.items
    assert {item.canonical_url for item in alice.items} != {item.canonical_url for item in bob.items}

    chosen = alice.items[0]
    approved = record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=chosen.candidate_id,
        decision="approved",
    )
    ignored = record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=alice.items[1].candidate_id,
        decision="ignored",
    )
    assert approved.recommendation_status == "approved"
    assert ignored.recommendation_status == "ignored"

    visible = list_source_recommendations_for_user(database, "user_a")
    assert all(item.candidate_id != ignored.candidate_id for item in visible.items)
    assert any(item.recommendation_status == "approved" for item in visible.items)

    bob_after = list_source_recommendations_for_user(database, "user_b")
    assert all(item.recommendation_status == "pending" for item in bob_after.items)
    assert _count(database, "source_sync_subscriptions") == before_subs
    assert _count(database, "source_sync_jobs") == before_jobs
    assert _count(database, "observations") == 0
    assert _count(database, "state_claims") == 0


def test_approve_supported_family_creates_subscription_and_sync_job(database, monkeypatch) -> None:
    monkeypatch.setenv("BULLETFEED_RSS_ALLOWED_HOSTS", "react.dev")
    get_settings.cache_clear()
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "user_a", topics=(("React", "high"),))
    items = list_source_recommendations_for_user(database, "user_a").items
    rss = next(item for item in items if item.family == SourceKind.RSS_ATOM.value)
    docs = next(item for item in items if item.family == SourceKind.GENERIC_WEB.value)
    record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=rss.candidate_id,
        decision="approved",
    )
    record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=docs.candidate_id,
        decision="approved",
    )
    record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=rss.candidate_id,
        decision="approved",
    )
    assert _count(database, "source_sync_subscriptions") == 1
    assert _count(database, "source_sync_jobs") == 1
    with database.connect() as connection:
        users = connection.execute(
            "SELECT user_id FROM source_sync_subscription_users"
        ).fetchall()
    assert [row["user_id"] for row in users] == ["user_a"]


def test_ignore_and_discovery_only_do_not_create_sync_jobs(database) -> None:
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "user_a", topics=(("React", "high"),))
    items = list_source_recommendations_for_user(database, "user_a").items
    ignored = record_source_recommendation_decision(
        database,
        user_id="user_a",
        candidate_id=items[0].candidate_id,
        decision="ignored",
    )
    assert ignored.recommendation_status == "ignored"
    assert _count(database, "source_sync_subscriptions") == 0
    assert _count(database, "source_sync_jobs") == 0


def test_api_lists_and_decides_without_subscribing(
    client: TestClient,
    auth_headers,
    database: Database,
) -> None:
    created = client.post(
        "/v1/me/topics",
        headers=auth_headers,
        json={"name": "React", "type": "technology"},
    )
    assert created.status_code == 201
    listed = client.get("/v1/me/source-recommendations", headers=auth_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert body["version"] == SOURCE_DISCOVERY_VERSION
    assert body["items"]
    first = body["items"][0]
    assert first["evidenceEligible"] is False
    assert first["reason"]
    assert first["explanation"]
    assert first["discoveryProvenance"]
    assert first["family"]

    decided = client.post(
        f"/v1/me/source-recommendations/{first['id']}",
        headers=auth_headers,
        json={"decision": "approved"},
    )
    assert decided.status_code == 200
    assert decided.json()["recommendationStatus"] == "approved"
    assert decided.json()["evidenceEligible"] is False
    assert _count(database, "source_sync_subscriptions") == 0
    assert _count(database, "source_sync_jobs") == 0
    assert client.get("/v1/me/source-recommendations").status_code == 401
    missing = client.post(
        "/v1/me/source-recommendations/ep_does_not_exist",
        headers=auth_headers,
        json={"decision": "ignored"},
    )
    assert missing.status_code == 404


def test_gold_fixture_measures_precision_and_recall() -> None:
    gold = load_source_discovery_gold(_GOLD)
    report = evaluate_source_discovery(gold, registry=SourceRegistry())
    assert report.cases
    assert report.mean_precision >= 0.5
    assert report.mean_recall >= 0.45
    for case, score in zip(gold.cases, report.cases, strict=True):
        haystack = " ".join(score.predicted).casefold()
        for needle in case.irrelevant_substrings:
            assert needle.casefold() not in haystack
        assert score.precision >= case.min_precision, (case.case_id, score.precision, score.predicted)
        assert score.recall >= case.min_recall, (case.case_id, score.recall, score.predicted)


def test_selected_repository_emits_official_github_releases() -> None:
    state = _state("u_repo", repositories=(("facebook/react", "javascript"),))
    result = discover_sources(state, SourceRegistry(seed_mvp=False))
    urls = {item.canonical_url for item in result.items}
    assert canonicalize_url("https://github.com/facebook/react/releases") in urls
    release = next(
        item
        for item in result.items
        if item.canonical_url == canonicalize_url("https://github.com/facebook/react/releases")
    )
    assert release.family == SourceKind.GITHUB_RELEASE.value
    assert release.discovery_provenance == DiscoveryProvenance.REPOSITORY_METADATA
    assert release.evidence_eligible is False


def test_revision_14_adds_discovery_decisions_and_preserves_ledger(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-discovery.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '14'")
        connection.execute("DROP TABLE IF EXISTS source_discovery_decisions")
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (
                'obs_sd', 'statuspage', 'abcd1234', 'inc_sd',
                'hash', '{}', 'https://example.test', '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO ledger_events (
                id, source_type, source_key, source_event_id, title, created_at
            ) VALUES (
                'event_sd', 'statuspage', 'abcd1234', 'inc_sd', 'Legacy',
                '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO state_claims (
                id, event_id, observation_id, slot, value_text, detail_text,
                valid_at, observed_at
            ) VALUES (
                'claim_sd', 'event_sd', 'obs_sd', 'status', 'investigating', 'Legacy',
                '2026-08-22T00:00:00Z', '2026-08-22T00:00:00Z'
            )
            """
        )

    database.initialize()
    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        from app.db.migrations import KNOWN_REVISIONS

        assert revisions == set(KNOWN_REVISIONS)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(source_discovery_decisions)")}
        assert {"user_id", "candidate_id", "decision", "decided_at"} <= columns
        claim = connection.execute("SELECT value_text FROM state_claims WHERE id = 'claim_sd'").fetchone()
        assert claim["value_text"] == "investigating"
        assert connection.execute("SELECT COUNT(*) FROM source_discovery_decisions").fetchone()[0] == 0
