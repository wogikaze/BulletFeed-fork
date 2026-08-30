from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import Database
from app.db.topic_catalog import install_topic_catalog
from app.evaluation.personalization_gold import load_personalization_gold
from app.services.cold_start_policy import COLD_START_POLICY_VERSION
from app.services.event_concepts import EventConcept
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.services.topic_recommendations import (
    TOPIC_RECOMMENDATION_VERSION,
    recommend_topics,
    recommend_topics_for_user,
    topic_identity,
)
from app.services.user_interest import (
    InterestSources,
    rebuild_user_interest,
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
    return rebuild_user_interest(user_id, signals_from_sources(sources))


def _seed_user(
    connection: sqlite3.Connection,
    user_id: str,
    *,
    topics: tuple[tuple[str, str], ...] = (),
    repos: tuple[str, ...] = (),
    occupation: str = "",
    interests: tuple[str, ...] = (),
) -> None:
    connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", (user_id,))
    if occupation or interests:
        connection.execute(
            """
            INSERT INTO profiles (user_id, occupation, interests_json, region, updated_at)
            VALUES (?, ?, ?, '', 1)
            """,
            (user_id, occupation, json.dumps(list(interests))),
        )
    for index, (name, priority) in enumerate(topics):
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES (?, ?, ?, 'technology', ?, ?, 1)
            """,
            (f"{user_id}-topic-{index}", user_id, name, priority, index),
        )
    for index, full_name in enumerate(repos):
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES (?, ?, ?, ?, 1, 0)
            """,
            (user_id, f"repo-{user_id}-{index}", full_name, f"https://github.com/{full_name}"),
        )


def _names(result) -> list[str]:
    return [item.name for item in result.items]


def _event_concept(
    concept_id: str,
    canonical_name: str,
    *,
    weight: float = 0.9,
    aliases: tuple[str, ...] = (),
    provenance: str = "test",
) -> EventConcept:
    return EventConcept(
        concept_id=concept_id,
        canonical_name=canonical_name,
        concept_type="framework_library_package",
        weight=weight,
        confidence="high",
        stable_id=None,
        aliases=aliases,
        product_version=None,
        source="prose",
        provenance=provenance,
    )


def test_strong_positive_recommends_followed_topic_as_explicit() -> None:
    state = _state("u_react", topics=(("React", "high"),))
    result = recommend_topics(state, followed_names=("React",))

    assert result.version == TOPIC_RECOMMENDATION_VERSION
    react = next(item for item in result.items if topic_identity(item.name) == "react")
    assert react.provenance == "explicit"
    assert react.already_followed is True
    assert react.score > 0
    assert "explicit" in react.reason.casefold() or "interest" in react.reason.casefold()


def test_semantic_neighbor_is_recommended_without_string_equality() -> None:
    state = _state("u_compiler", topics=(("compiler optimization", "high"),))
    result = recommend_topics(state, followed_names=("compiler optimization",))
    names = {topic_identity(name) for name in _names(result)}

    assert "llvm-scalar-evolution" in names or "llvm" in names
    neighbor = next(
        item
        for item in result.items
        if topic_identity(item.name) in {"llvm", "llvm-scalar-evolution"}
    )
    assert neighbor.provenance == "inferred"
    assert neighbor.already_followed is False
    assert "neighbor" in neighbor.reason.casefold()


def test_aliases_and_duplicates_canonicalize_to_one_topic() -> None:
    state = _state(
        "u_alias",
        topics=(("React", "high"), ("react.js", "normal")),
        repositories=(("facebook/react", "JavaScript"),),
    )
    result = recommend_topics(state, followed_names=("React", "react.js"))
    react_items = [item for item in result.items if topic_identity(item.name) == "react"]

    assert len(react_items) == 1
    assert react_items[0].name == "React"
    assert react_items[0].already_followed is True


def test_hard_negatives_are_not_recommended() -> None:
    react = _state("u_react", topics=(("React", "high"),))
    result = recommend_topics(
        react,
        followed_names=("React",),
        event_concepts=(
            _event_concept("project-reactor", "Project Reactor", aliases=("reactor", "reactor-core")),
            _event_concept("reactos", "ReactOS"),
            _event_concept("nuclear-reactor", "nuclear reactor"),
        ),
    )
    blob = " ".join(_names(result)).casefold()
    identities = {topic_identity(name) for name in _names(result)}

    assert "react" in identities
    assert "reactor" not in blob
    assert "project reactor" not in blob
    assert "reactos" not in blob
    assert "nuclear" not in blob
    assert "project-reactor" not in identities
    assert all(
        "reactor" not in item.reason.casefold() or "hard" in item.reason.casefold()
        for item in result.items
    )


def test_low_confidence_candidates_abstain() -> None:
    state = _state("u_weak", inferred=("webpack",))
    result = recommend_topics(state, limit=10)
    weak = [item for item in result.items if "webpack" in item.name.casefold()]
    assert weak == [] or all(item.score >= 0.12 for item in result.items)


def test_cold_start_uses_catalog_fallback_labeled_inferred() -> None:
    state = _state("u_cold", occupation="student")
    result = recommend_topics(state, followed_names=())

    assert result.items
    assert result.policy_version == COLD_START_POLICY_VERSION
    assert result.cohort == "empty_profile"
    assert all(item.provenance == "inferred" for item in result.items)
    assert all(item.already_followed is False for item in result.items)
    assert any("catalog" in item.reason.casefold() for item in result.items)
    assert any("catalog:fallback" in item.source_signals for item in result.items)
    assert all(item.provenance != "explicit" for item in result.items)
    assert all("not an explicit" in item.reason.casefold() for item in result.items)


def test_already_followed_marked_or_excluded_deterministically() -> None:
    state = _state("u_mark", topics=(("React", "high"), ("TypeScript", "high")))
    included = recommend_topics(state, followed_names=("React", "TypeScript"), include_followed=True)
    excluded = recommend_topics(state, followed_names=("React", "TypeScript"), include_followed=False)

    followed_included = {item.name for item in included.items if item.already_followed}
    assert {"React", "TypeScript"} <= followed_included
    assert all(not item.already_followed for item in excluded.items)
    assert not {"React", "TypeScript"} & {item.name for item in excluded.items}


def test_tenant_isolation(database: Database) -> None:
    install_topic_catalog(database)
    with database.connect() as connection:
        _seed_user(connection, "tenant_a", topics=(("React", "high"),), repos=("facebook/react",))
        _seed_user(connection, "tenant_b", topics=(("Go", "high"),), repos=("golang/go",))
        alice = recommend_topics_for_user(connection, "tenant_a")
        bob = recommend_topics_for_user(connection, "tenant_b")

    assert alice.tenant_id == "tenant_a"
    assert bob.tenant_id == "tenant_b"
    alice_ids = {topic_identity(name) for name in _names(alice)}
    bob_ids = {topic_identity(name) for name in _names(bob)}
    assert "react" in alice_ids
    assert "go" in bob_ids
    assert "go" not in {topic_identity(item.name) for item in alice.items if item.provenance == "explicit"}
    assert "react" not in {topic_identity(item.name) for item in bob.items if item.provenance == "explicit"}


def test_does_not_auto_add_topics(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/v1/me/topics",
        headers=auth_headers,
        json={"name": "React", "type": "technology"},
    )
    assert created.status_code == 201
    before = client.get("/v1/me/topics", headers=auth_headers)
    assert before.status_code == 200
    assert len(before.json()["items"]) == 1

    recommended = client.get("/v1/me/topic-recommendations", headers=auth_headers)
    assert recommended.status_code == 200
    body = recommended.json()
    assert body["version"] == TOPIC_RECOMMENDATION_VERSION
    assert body["policyVersion"] == COLD_START_POLICY_VERSION
    assert body["cohort"] in {
        "empty_profile",
        "profile_only",
        "topic_selected",
        "github_connected",
        "history_rich",
    }
    assert body["items"]
    first = body["items"][0]
    required = {
        "id",
        "name",
        "type",
        "score",
        "reason",
        "provenance",
        "alreadyFollowed",
        "confidence",
        "sourceSignals",
    }
    assert required <= set(first)
    assert first["provenance"] in {"explicit", "inferred"}

    after = client.get("/v1/me/topics", headers=auth_headers)
    before_names = [item["name"] for item in before.json()["items"]]
    after_names = [item["name"] for item in after.json()["items"]]
    assert after_names == before_names


def test_api_requires_auth_and_is_distinct_from_search(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    assert client.get("/v1/me/topic-recommendations").status_code == 401

    search = client.get("/v1/topics/search", headers=auth_headers, params={"q": "cloud"})
    recommended = client.get("/v1/me/topic-recommendations", headers=auth_headers)
    assert search.status_code == 200
    assert recommended.status_code == 200
    assert "version" in recommended.json()
    assert "version" not in search.json()
    assert recommended.json()["items"]
    assert "abstentions" in recommended.json()
    assert all(item.get("provenance") == "inferred" for item in recommended.json()["items"])
    assert any("catalog" in item["reason"].casefold() for item in recommended.json()["items"])


def test_api_cohorts_change_and_ignore_hides_candidate(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    empty = client.get("/v1/me/topic-recommendations", headers=auth_headers)
    assert empty.status_code == 200
    assert empty.json()["cohort"] == "empty_profile"
    empty_names = [item["name"] for item in empty.json()["items"]]

    created = client.post(
        "/v1/me/topics",
        headers=auth_headers,
        json={"name": "React", "type": "technology"},
    )
    assert created.status_code == 201
    selected = client.get("/v1/me/topic-recommendations", headers=auth_headers)
    assert selected.status_code == 200
    assert selected.json()["cohort"] == "topic_selected"
    selected_names = [item["name"] for item in selected.json()["items"]]
    assert selected_names != empty_names

    first = selected.json()["items"][0]
    ignored = client.post(
        f"/v1/me/topic-recommendations/{first['id']}",
        headers=auth_headers,
        json={"decision": "ignored"},
    )
    assert ignored.status_code == 200
    assert all(item["id"] != first["id"] for item in ignored.json()["items"])
    missing = client.post(
        "/v1/me/topic-recommendations/unknown-topic",
        headers=auth_headers,
        json={"decision": "ignored"},
    )
    assert missing.status_code == 404


def test_api_github_and_history_cohorts_change_candidates(
    client: TestClient,
    database: Database,
) -> None:
    session = client.post("/v1/sessions")
    assert session.status_code == 200
    user_id = session.json()["userId"]
    headers = {"Authorization": f"Bearer {session.json()['accessToken']}"}
    empty = client.get("/v1/me/topic-recommendations", headers=headers)
    assert empty.json()["cohort"] == "empty_profile"
    empty_ids = [item["id"] for item in empty.json()["items"]]

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES (?, ?, ?, ?, 1, 0)
            """,
            (user_id, "repo-react", "facebook/react", "https://github.com/facebook/react"),
        )
    github = client.get("/v1/me/topic-recommendations", headers=headers)
    assert github.json()["cohort"] == "github_connected"
    github_ids = [item["id"] for item in github.json()["items"]]
    assert github_ids != empty_ids


def test_gold_precision_of_recommended_names_vs_user_relevant_topics() -> None:
    corpus = load_personalization_gold(_V01).for_split("pilot")
    precisions: list[float] = []
    react_precision = 0.0

    for user in corpus.users:
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
        state = state_from_personalization_user(
            user.user_id,
            occupation=user.profile.occupation,
            interests=user.profile.interests,
            topics=tuple((topic.name, topic.priority) for topic in user.topics),
            repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
            prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
        )
        result = recommend_topics(
            state,
            followed_names=tuple(topic.name for topic in user.topics),
            limit=5,
        )
        top = [topic_identity(item.name) for item in result.items[:5]]
        if not top:
            precisions.append(0.0)
            continue
        precision = sum(1 for key in top if key in relevant) / len(top)
        precisions.append(precision)
        if "react" in user.products and user.kind == "history_rich":
            react_precision = precision
            assert "reactor" not in " ".join(_names(result)).casefold()
            assert "project-reactor" not in top

    assert precisions
    mean_precision = sum(precisions) / len(precisions)
    assert mean_precision > 0.3
    assert react_precision >= 0.6


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
                "id": "inc_topic_rec_ledger",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_topic_rec_ledger",
                "incident_updates": [
                    {
                        "id": "upd_topic_rec_ledger",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "display_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def test_recommendation_does_not_mutate_ledger(tmp_path: Path) -> None:
    clean = Database(tmp_path / "rec-clean.db")
    clean.initialize()
    noisy = Database(tmp_path / "rec-noisy.db")
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
        _seed_user(
            connection,
            "rec_user",
            topics=(("React", "high"),),
            repos=("facebook/react",),
            occupation="frontend engineer",
            interests=("ui",),
        )
        recommended = recommend_topics_for_user(connection, "rec_user")
    after = _world_ledger_snapshot(noisy)
    clean_snapshot = _world_ledger_snapshot(clean)

    assert recommended.items
    assert before == after
    assert after == clean_snapshot
    assert after["observation_count"] == 1
