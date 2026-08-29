from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from app.database import Database
from app.services.inferred_priors import (
    INFERENCE_VERSION,
    SIGNAL_WEIGHTS,
    InferredInterestSignal,
    SignalType,
    empty_inferred_priors,
    inspect_inferred_priors_for_user,
    load_inferred_signals,
    make_inferred_signal,
    persist_inferred_signals,
    rebuild_inferred_priors,
    rebuild_inferred_priors_for_user,
    reset_inferred_priors_for_user,
    withdraw_persisted_repository,
    withdraw_repository,
)
from app.services.ledger_projection import LedgerProjector
from app.services.repository_topic_inference import infer_prior_signals
from app.services.statuspage_pipeline import StatuspagePipeline
from app.services.user_interest import (
    InterestSources,
    load_user_interest,
    rebuild_user_interest,
    signals_from_sources,
)

_OBSERVED = "2026-08-29T00:00:00Z"


def _signal(
    repository: str,
    signal_type: SignalType,
    topic_name: str,
    *,
    inference_version: str = INFERENCE_VERSION,
    observed_at: str = _OBSERVED,
    weight: float | None = None,
) -> InferredInterestSignal:
    signal = make_inferred_signal(
        repository=repository,
        signal_type=signal_type,
        topic_name=topic_name,
        observed_at=observed_at,
        inference_version=inference_version,
    )
    assert signal is not None
    if weight is not None:
        return replace(signal, weight=weight, inference_version=inference_version)
    return replace(signal, inference_version=inference_version)


def _seed_user(
    connection,
    user_id: str,
    *,
    topics: tuple[str, ...] = (),
    repos: tuple[str, ...] = (),
) -> None:
    connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", (user_id,))
    for index, name in enumerate(topics):
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES (?, ?, ?, 'technology', 'high', ?, 1)
            """,
            (f"{user_id}-topic-{index}", user_id, name, index),
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


def test_each_inferred_interest_records_provenance() -> None:
    signal = _signal("acme/web", "language", "JavaScript")
    assert signal.repository == "acme/web"
    assert signal.signal_type == "language"
    assert signal.weight == SIGNAL_WEIGHTS["language"]
    assert signal.inference_version == INFERENCE_VERSION
    assert signal.observed_at == _OBSERVED
    assert INFERENCE_VERSION in signal.provenance()
    assert "language" in signal.provenance()
    assert "acme/web" in signal.provenance()


def test_signal_types_use_different_weights() -> None:
    weights = {
        signal_type: _signal("acme/web", signal_type, "TypeScript").weight
        for signal_type in SIGNAL_WEIGHTS
    }
    assert weights["language"] > weights["dependency"]
    assert weights["dependency"] > weights["repository_topic"]
    assert weights["repository_topic"] > weights["build_tool"]
    assert weights["build_tool"] > weights["dev_dependency"]
    assert len(set(weights.values())) == len(weights)


def test_explicit_topics_remain_separate_and_stronger() -> None:
    inferred = rebuild_inferred_priors(
        "user_mix",
        (_signal("facebook/react", "language", "JavaScript"),),
    )
    state = rebuild_user_interest(
        "user_mix",
        signals_from_sources(
            InterestSources(
                topics=(("React", "high"),),
                inferred_priors=inferred.signals,
            )
        ),
    )
    concepts = {concept.concept_id: concept for concept in state.concepts}
    react = concepts["react"]
    javascript = concepts["javascript"]
    assert react.origin == "explicit"
    assert javascript.origin == "inferred"
    assert react.weight > javascript.weight
    assert all(signal.origin == "inferred" for signal in javascript.sources)
    assert any(signal.kind == "explicit_topic" for signal in react.sources)


def test_add_and_remove_repository_withdraws_only_that_repo(database: Database) -> None:
    with database.connect() as connection:
        _seed_user(connection, "user_a", topics=("React",), repos=("acme/web", "acme/api"))
        persist_inferred_signals(
            connection,
            "user_a",
            (
                _signal("acme/web", "language", "JavaScript"),
                _signal("acme/web", "dev_dependency", "webpack"),
                _signal("acme/api", "language", "JavaScript"),
                _signal("acme/api", "dependency", "FastAPI"),
            ),
        )
        added = rebuild_inferred_priors_for_user(connection, "user_a")
        names = {prior.display_name.casefold() for prior in added.priors}
        assert {"javascript", "webpack", "fastapi"} <= names

        connection.execute(
            "DELETE FROM github_repo_watches WHERE user_id = ? AND full_name = ?",
            ("user_a", "acme/web"),
        )
        withdraw_persisted_repository(connection, "user_a", "acme/web")
        removed = rebuild_inferred_priors_for_user(connection, "user_a")

    leftover = {prior.display_name.casefold() for prior in removed.priors}
    assert leftover == {"javascript", "fastapi"}
    assert all(signal.repository == "acme/api" for signal in removed.signals)
    with database.connect() as connection:
        interest = load_user_interest(connection, "user_a")
        topics = [
            row["name"]
            for row in connection.execute("SELECT name FROM topics WHERE user_id = 'user_a'")
        ]
    assert "React" in topics
    assert any(
        concept.concept_id == "react" and concept.origin == "explicit"
        for concept in interest.concepts
    )


def test_overlapping_repositories_aggregate_deterministically() -> None:
    first = rebuild_inferred_priors(
        "user_overlap",
        (
            _signal("acme/web", "language", "JavaScript"),
            _signal("acme/api", "language", "JavaScript"),
            _signal("acme/web", "dependency", "React"),
        ),
    )
    second = rebuild_inferred_priors(
        "user_overlap",
        (
            _signal("acme/web", "dependency", "React"),
            _signal("acme/api", "language", "JavaScript"),
            _signal("acme/web", "language", "JavaScript"),
        ),
    )
    assert first.signal_fingerprint == second.signal_fingerprint
    assert first.priors == second.priors
    javascript = first.prior_map()["javascript"]
    assert len(javascript.sources) == 2
    assert {source.repository for source in javascript.sources} == {"acme/web", "acme/api"}
    assert javascript.weight > SIGNAL_WEIGHTS["language"]
    assert javascript.weight <= 0.65


def test_dev_only_dependency_is_weaker_than_runtime() -> None:
    observed = infer_prior_signals(
        {},
        [],
        {
            "package.json": json.dumps(
                {
                    "dependencies": {"react": "^19.0.0"},
                    "devDependencies": {"webpack": "^5.90.0", "vite": "^6.0.0"},
                }
            )
        },
        repository="acme/web",
        observed_at=_OBSERVED,
    )
    by_topic = {signal.topic_name.casefold(): signal for signal in observed}
    assert by_topic["webpack"].signal_type == "dev_dependency"
    assert by_topic["vite"].signal_type == "dev_dependency"
    assert by_topic["react"].signal_type == "dependency"
    assert by_topic["react"].weight > by_topic["webpack"].weight

    runtime_only = infer_prior_signals(
        {},
        [],
        {"package.json": json.dumps({"dependencies": {"webpack": "^5.90.0"}})},
        repository="acme/lib",
        observed_at=_OBSERVED,
    )
    webpack_runtime = next(signal for signal in runtime_only if signal.topic_name.casefold() == "webpack")
    assert webpack_runtime.signal_type == "dependency"
    assert webpack_runtime.weight > by_topic["webpack"].weight


def test_stale_inference_rebuild_restamps_current_weights(database: Database) -> None:
    stale = _signal(
        "acme/web",
        "language",
        "JavaScript",
        inference_version="inferred-priors-v0",
        weight=0.99,
    )
    rebuilt = rebuild_inferred_priors("user_stale", (stale,))
    assert rebuilt.inference_version == INFERENCE_VERSION
    assert rebuilt.signals[0].inference_version == INFERENCE_VERSION
    assert rebuilt.signals[0].weight == SIGNAL_WEIGHTS["language"]
    assert rebuilt.signals[0].weight != 0.99

    with database.connect() as connection:
        _seed_user(connection, "user_stale", repos=("acme/web",))
        persist_inferred_signals(connection, "user_stale", (stale,))
        stored = load_inferred_signals(connection, "user_stale")
        assert stored[0].inference_version == "inferred-priors-v0"
        state = rebuild_inferred_priors_for_user(connection, "user_stale")
        refreshed = load_inferred_signals(connection, "user_stale")
    assert state.inference_version == INFERENCE_VERSION
    assert refreshed[0].inference_version == INFERENCE_VERSION
    assert refreshed[0].weight == SIGNAL_WEIGHTS["language"]


def test_inspect_and_reset_does_not_delete_explicit_topics(database: Database) -> None:
    with database.connect() as connection:
        _seed_user(connection, "user_reset", topics=("React", "FastAPI"), repos=("acme/web",))
        persist_inferred_signals(
            connection,
            "user_reset",
            (
                _signal("acme/web", "language", "JavaScript"),
                _signal("acme/web", "build_tool", "Vite"),
            ),
        )
        inspected = inspect_inferred_priors_for_user(connection, "user_reset")
        assert inspected.inspect()
        assert {prior.display_name.casefold() for prior in inspected.priors} >= {"javascript", "vite"}
        before_topics = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM topics WHERE user_id = 'user_reset' ORDER BY name"
            )
        ]
        reset = reset_inferred_priors_for_user(connection, "user_reset")
        after_topics = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM topics WHERE user_id = 'user_reset' ORDER BY name"
            )
        ]
        leftover_signals = load_inferred_signals(connection, "user_reset")
        interest = load_user_interest(connection, "user_reset")

    assert reset.priors == ()
    assert reset.signals == ()
    assert leftover_signals == ()
    assert before_topics == after_topics == ["FastAPI", "React"]
    assert {concept.concept_id for concept in interest.explicit_concepts()} >= {"react", "fastapi"}
    assert not any(
        concept.concept_id == "javascript" and not concept.suppressed
        for concept in interest.inferred_concepts()
    )


def test_withdraw_repository_is_rebuildable_without_persistence() -> None:
    state = rebuild_inferred_priors(
        "user_mem",
        (
            _signal("acme/web", "language", "TypeScript"),
            _signal("acme/api", "language", "Go"),
        ),
    )
    withdrawn = withdraw_repository(state, "acme/web")
    assert {prior.display_name for prior in withdrawn.priors} == {"Go"}
    assert empty_inferred_priors("user_mem").priors == ()


def _world_ledger_snapshot(database: Database) -> dict[str, object]:
    with database.connect() as connection:
        observations = list(connection.execute("SELECT id, payload_hash FROM observations ORDER BY id"))
        events = list(connection.execute("SELECT id FROM ledger_events ORDER BY id"))
        claims = list(connection.execute("SELECT id FROM state_claims ORDER BY id"))
        relations = list(connection.execute("SELECT id FROM claim_relations ORDER BY id"))
        deltas = list(connection.execute("SELECT id FROM deltas ORDER BY id"))
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


def test_inferred_prior_rebuild_does_not_change_event_claim_ledger(tmp_path: Path) -> None:
    clean = Database(tmp_path / "prior-clean.db")
    clean.initialize()
    noisy = Database(tmp_path / "prior-noisy.db")
    noisy.initialize()
    summary = {
        "incidents": [
            {
                "id": "inc_prior_ledger",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_prior_ledger",
                "incident_updates": [
                    {
                        "id": "upd_prior_ledger",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "display_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }
    StatuspagePipeline(clean).ingest_summary(
        page_id="abcd1234",
        summary=summary,
        retrieved_at="2026-08-22T00:11:00Z",
    )
    result = StatuspagePipeline(noisy).ingest_summary(
        page_id="abcd1234",
        summary=summary,
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(clean).project_event(event_id)
    LedgerProjector(noisy).project_event(event_id)

    before = _world_ledger_snapshot(noisy)
    with noisy.connect() as connection:
        _seed_user(connection, "prior_user", topics=("React",), repos=("acme/web",))
        persist_inferred_signals(
            connection,
            "prior_user",
            (_signal("acme/web", "language", "JavaScript"),),
        )
        rebuild_inferred_priors_for_user(connection, "prior_user")
        load_user_interest(connection, "prior_user")
        reset_inferred_priors_for_user(connection, "prior_user")
    after = _world_ledger_snapshot(noisy)
    assert before == after
    assert after == _world_ledger_snapshot(clean)
