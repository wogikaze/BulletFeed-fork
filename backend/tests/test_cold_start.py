from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import Database
from app.db.topic_catalog import install_topic_catalog
from app.evaluation.personalization_gold import evaluate_personalization, load_personalization_gold
from app.services.cold_start_policy import (
    CATALOG_FALLBACK_SCORE,
    COLD_START_POLICY_VERSION,
    EXPLICIT_INTEREST_FLOOR,
    FIRST_FEEDBACK_SCORE_DELTA,
    IRRELEVANT_ITEM_RATE_CEILING,
    PRECISION_AT_5_FLOOR,
    TOPIC_REC_PRECISION_AT_5_FLOOR,
    classify_cohort,
    classify_cohort_from_sources,
    classify_personalization_user,
    explicit_outranks_catalog,
    is_first_feedback,
)
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.services.topic_recommendations import recommend_topics, recommend_topics_for_user, topic_identity
from app.services.user_interest import (
    InterestSources,
    rebuild_user_interest,
    semantic_match,
    signals_from_sources,
    state_from_personalization_user,
)

_V01 = Path(__file__).parent / "gold" / "personalization" / "v01"


def _state(
    user_id: str,
    *,
    topics: tuple[tuple[str, str], ...] = (),
    repositories: tuple[tuple[str, str], ...] = (),
    occupation: str = "",
    interests: tuple[str, ...] = (),
    feedback: tuple[tuple[str, str], ...] = (),
    inferred: tuple[str, ...] = (),
):
    sources = InterestSources(
        topics=topics,
        repositories=repositories,
        occupation=occupation,
        profile_interests=interests,
        feedback=feedback,
        inferred_technologies=inferred,
    )
    return rebuild_user_interest(user_id, signals_from_sources(sources)), sources


def _names(result) -> list[str]:
    return [item.name for item in result.items]


def test_policy_is_versioned_and_classifies_cohorts() -> None:
    empty, empty_sources = _state("u_empty", occupation="student")
    profile, profile_sources = _state("u_profile", occupation="designer", interests=("ui",))
    topics, topic_sources = _state("u_topics", topics=(("React", "high"),))
    github, github_sources = _state("u_gh", repositories=(("facebook/react", "JavaScript"),))
    rich, rich_sources = _state(
        "u_rich",
        topics=(("React", "high"),),
        repositories=(("facebook/react", "JavaScript"),),
        feedback=(("React 18 upgrade notes", "important"), ("unrelated rust blog", "not_relevant")),
    )

    assert COLD_START_POLICY_VERSION.startswith("cold-start-v")
    assert classify_cohort(empty) == classify_cohort_from_sources(empty_sources) == "empty_profile"
    assert classify_cohort(profile) == classify_cohort_from_sources(profile_sources) == "profile_only"
    assert classify_cohort(topics) == classify_cohort_from_sources(topic_sources) == "topic_selected"
    assert classify_cohort(github) == classify_cohort_from_sources(github_sources) == "github_connected"
    assert classify_cohort(rich) == classify_cohort_from_sources(rich_sources) == "history_rich"
    assert explicit_outranks_catalog(EXPLICIT_INTEREST_FLOOR, CATALOG_FALLBACK_SCORE)


def test_empty_profile_catalog_fallback_is_inferred_not_explicit() -> None:
    state, _sources = _state("u_empty", occupation="student")
    result = recommend_topics(state)

    assert result.cohort == "empty_profile"
    assert result.policy_version == COLD_START_POLICY_VERSION
    assert result.items
    assert all(item.provenance == "inferred" for item in result.items)
    assert all("catalog:fallback" in item.source_signals for item in result.items)
    assert all("catalog" in item.reason.casefold() for item in result.items)
    assert all("not an explicit" in item.reason.casefold() for item in result.items)
    assert all(item.score <= CATALOG_FALLBACK_SCORE for item in result.items)
    assert all(item.already_followed is False for item in result.items)


def test_github_priors_do_not_require_feedback_history() -> None:
    state, _sources = _state("u_gh", repositories=(("facebook/react", "JavaScript"),))
    result = recommend_topics(state)

    assert result.cohort == "github_connected"
    assert not is_first_feedback(state)
    identities = {topic_identity(name) for name in _names(result)}
    assert "react" in identities
    assert not all("catalog:fallback" in item.source_signals for item in result.items)
    react = next(item for item in result.items if topic_identity(item.name) == "react")
    assert react.score > CATALOG_FALLBACK_SCORE


def test_catalog_cannot_overwhelm_explicit_interests() -> None:
    state, _sources = _state("u_react", topics=(("React", "high"),))
    result = recommend_topics(state)

    assert result.cohort == "topic_selected"
    explicit = [item for item in result.items if item.provenance == "explicit"]
    catalog = [item for item in result.items if "catalog:fallback" in item.source_signals]
    assert explicit
    assert catalog == []
    assert all(item.score >= EXPLICIT_INTEREST_FLOOR for item in explicit)
    assert all(item.score > CATALOG_FALLBACK_SCORE for item in explicit)


def test_first_feedback_changes_ranking_without_replacing_state() -> None:
    base, _ = _state("u_fb", topics=(("React", "high"),))
    with_fb, _ = _state(
        "u_fb",
        topics=(("React", "high"),),
        feedback=(("Rust memory safety release", "important"),),
    )
    before = recommend_topics(base)
    after = recommend_topics(with_fb)

    assert classify_cohort(base) == "topic_selected"
    assert classify_cohort(with_fb) == "history_rich"
    assert is_first_feedback(with_fb)
    assert {concept.concept_id for concept in with_fb.explicit_concepts()} >= {"react"}

    react_before = next(item for item in before.items if topic_identity(item.name) == "react")
    react_after = next(item for item in after.items if topic_identity(item.name) == "react")
    assert react_after.provenance == "explicit"
    assert abs(react_after.score - react_before.score) <= FIRST_FEEDBACK_SCORE_DELTA + 1e-9

    rust = [item for item in after.items if topic_identity(item.name) == "rust"]
    if rust:
        assert rust[0].score <= FIRST_FEEDBACK_SCORE_DELTA + 1e-9
        assert rust[0].provenance == "inferred"
        assert "feedback:bounded" in rust[0].source_signals


def test_gold_users_cover_empty_github_and_history_rich_cohorts() -> None:
    corpus = load_personalization_gold(_V01)
    cohorts = {
        user.user_id: classify_personalization_user(
            topics=tuple(topic.name for topic in user.topics),
            repositories=tuple(repo.full_name for repo in user.repositories),
            profile_interests=user.profile.interests,
            prior_feedback=user.prior_feedback,
        )
        for user in corpus.users
    }
    assert "empty_profile" in cohorts.values()
    assert "github_connected" in cohorts.values()
    assert "history_rich" in cohorts.values()
    assert "topic_selected" in cohorts.values()
    assert {user.kind for user in corpus.users} >= {"cold_start", "history_rich"}


def test_gold_reports_cold_start_slice_and_topic_rec_floors() -> None:
    corpus = load_personalization_gold(_V01).for_split("pilot")
    items = corpus.item_by_id()
    rankings: dict[str, list[str]] = {}
    topic_precisions: list[float] = []

    for user in corpus.users:
        state = state_from_personalization_user(
            user.user_id,
            occupation=user.profile.occupation,
            interests=user.profile.interests,
            topics=tuple((topic.name, topic.priority) for topic in user.topics),
            repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
            prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
        )
        scored = [
            (
                semantic_match(
                    state,
                    f"{items[judgment.item_id].title} {items[judgment.item_id].summary}",
                ).score,
                judgment.item_id,
            )
            for judgment in corpus.judgments_for_user(user.user_id)
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        rankings[user.user_id] = [item_id for _score, item_id in scored]

        if user.kind != "cold_start":
            continue
        relevant = {
            topic_identity(name)
            for name in (
                *(topic.name for topic in user.topics),
                *user.products,
                *user.adjacent_products,
            )
            if name.strip()
        }
        if not relevant:
            continue
        recommended = recommend_topics(
            state,
            followed_names=tuple(topic.name for topic in user.topics),
            limit=5,
        )
        top = [topic_identity(item.name) for item in recommended.items[:5]]
        topic_precisions.append(sum(1 for key in top if key in relevant) / len(top) if top else 0.0)

    report = evaluate_personalization(corpus, rankings, k=5, split="pilot")
    assert "cold_start" in report.slices
    cold = report.slices["cold_start"]
    assert cold.precision_at_k >= PRECISION_AT_5_FLOOR
    assert cold.irrelevant_item_rate <= IRRELEVANT_ITEM_RATE_CEILING
    assert topic_precisions
    assert sum(topic_precisions) / len(topic_precisions) >= TOPIC_REC_PRECISION_AT_5_FLOOR


def test_does_not_auto_follow_topics_for_empty_profile(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    before = client.get("/v1/me/topics", headers=auth_headers)
    assert before.status_code == 200
    assert before.json()["items"] == []

    recommended = client.get("/v1/me/topic-recommendations", headers=auth_headers)
    assert recommended.status_code == 200
    body = recommended.json()
    assert body["policyVersion"] == COLD_START_POLICY_VERSION
    assert body["cohort"] == "empty_profile"
    assert body["items"]
    assert all(item["provenance"] == "inferred" for item in body["items"])
    assert all(item["alreadyFollowed"] is False for item in body["items"])

    after = client.get("/v1/me/topics", headers=auth_headers)
    assert after.json()["items"] == []


def _world_ledger_snapshot(database: Database) -> dict[str, object]:
    with database.connect() as connection:
        observations = list(
            connection.execute("SELECT id, payload_hash FROM observations ORDER BY id").fetchall()
        )
        events = list(connection.execute("SELECT id FROM ledger_events ORDER BY id").fetchall())
        claims = list(connection.execute("SELECT id FROM state_claims ORDER BY id").fetchall())
        relations = list(connection.execute("SELECT id FROM claim_relations ORDER BY id").fetchall())
        deltas = list(connection.execute("SELECT id FROM deltas ORDER BY id").fetchall())
        hashes = "".join(row["payload_hash"] for row in observations)
    return {
        "observation_count": len(observations),
        "event_count": len(events),
        "claim_count": len(claims),
        "relation_count": len(relations),
        "delta_count": len(deltas),
        "payload_hash": hashlib.sha256(hashes.encode("utf-8")).hexdigest(),
        "observation_ids": tuple(row["id"] for row in observations),
        "event_ids": tuple(row["id"] for row in events),
        "claim_ids": tuple(row["id"] for row in claims),
    }


def _statuspage_summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_cold_start_ledger",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_cold_start_ledger",
                "incident_updates": [
                    {
                        "id": "upd_cold_start_ledger",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "display_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def test_cold_start_recommendation_does_not_mutate_ledger(tmp_path: Path) -> None:
    clean = Database(tmp_path / "cold-clean.db")
    clean.initialize()
    noisy = Database(tmp_path / "cold-noisy.db")
    noisy.initialize()
    install_topic_catalog(clean)
    install_topic_catalog(noisy)

    StatuspagePipeline(clean).ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    result = StatuspagePipeline(noisy).ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(clean).project_event(event_id)
    LedgerProjector(noisy).project_event(event_id)

    before = _world_ledger_snapshot(noisy)
    with noisy.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", ("cold_user",))
        connection.execute(
            """
            INSERT INTO profiles (user_id, occupation, interests_json, region, updated_at)
            VALUES (?, ?, ?, '', 1)
            """,
            ("cold_user", "student", json.dumps([])),
        )
        recommended = recommend_topics_for_user(connection, "cold_user")
        topics_after = list(
            connection.execute("SELECT name FROM topics WHERE user_id = ?", ("cold_user",))
        )
    after = _world_ledger_snapshot(noisy)
    clean_snapshot = _world_ledger_snapshot(clean)

    assert recommended.cohort == "empty_profile"
    assert recommended.items
    assert topics_after == []
    assert before == after
    assert after == clean_snapshot
