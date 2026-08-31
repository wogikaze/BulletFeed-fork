from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from app.database import Database
from app.evaluation.personalization_gold import (
    evaluate_personalization,
    load_personalization_gold,
)
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.services.user_interest import (
    INTEREST_STATE_VERSION,
    InterestSources,
    detect_concepts_in_text,
    empty_user_interest,
    interest_concepts_for_user,
    load_user_interest,
    rebuild_user_interest,
    reset_user_interest,
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


def test_interest_state_is_versioned_and_rebuildable_from_signals() -> None:
    first = _state(
        "user_a",
        topics=(("compiler optimization", "high"),),
        repositories=(("llvm/llvm-project", "C++"),),
        occupation="compiler engineer",
        interests=("llvm",),
        feedback=(("LLVM mid-end notes", "important"),),
    )
    second = _state(
        "user_a",
        topics=(("compiler optimization", "high"),),
        repositories=(("llvm/llvm-project", "C++"),),
        occupation="compiler engineer",
        interests=("llvm",),
        feedback=(("LLVM mid-end notes", "important"),),
    )
    changed = _state(
        "user_a",
        topics=(("compiler optimization", "normal"),),
        repositories=(("llvm/llvm-project", "C++"),),
        occupation="compiler engineer",
        interests=("llvm",),
        feedback=(("LLVM mid-end notes", "important"),),
    )

    assert first.version == INTEREST_STATE_VERSION
    assert first.signal_fingerprint == second.signal_fingerprint
    assert first.concepts == second.concepts
    assert changed.signal_fingerprint != first.signal_fingerprint
    assert len(first.signal_fingerprint) == 64


def test_explicit_and_inferred_concepts_remain_distinguishable() -> None:
    state = _state(
        "user_mix",
        topics=(("React", "high"),),
        repositories=(("facebook/react", "JavaScript"),),
        inferred=("webpack",),
    )
    concepts = {concept.concept_id: concept for concept in interest_concepts_for_user(state)}

    assert concepts["react"].origin == "explicit"
    assert any(signal.kind == "explicit_topic" for signal in concepts["react"].sources)
    javascript = concepts.get("javascript")
    assert javascript is not None
    assert javascript.origin == "inferred"
    assert all(signal.origin == "inferred" for signal in javascript.sources)
    assert {concept.origin for concept in state.explicit_concepts()} == {"explicit"}
    assert {concept.origin for concept in state.inferred_concepts()} == {"inferred"}


def test_negative_evidence_does_not_erase_explicit_interests() -> None:
    state = _state(
        "user_keep",
        topics=(("React", "high"),),
        inferred=("javascript",),
        feedback=(
            ("unrelated rust blog", "not_relevant"),
            ("Project Reactor notes", "not_relevant"),
        ),
    )
    react = next(concept for concept in state.concepts if concept.concept_id == "react")
    assert react.origin == "explicit"
    assert react.suppressed is False
    assert react.weight >= 0.35
    assert semantic_match(state, "React 19.1.0 released with compiler fixes").matched


def test_negative_evidence_can_suppress_inferred_only_concepts() -> None:
    state = _state(
        "user_infer",
        inferred=("javascript",),
        feedback=(("JavaScript trivia newsletter", "not_relevant"),),
    )
    javascript = next(concept for concept in state.concepts if concept.concept_id == "javascript")
    assert javascript.origin == "inferred"
    assert javascript.suppressed is True
    assert javascript.weight == 0
    assert not semantic_match(state, "JavaScript Weekly issue 900").matched


def test_tenant_isolation_and_reset(database: Database) -> None:
    with database.connect() as connection:
        _seed_user(
            connection,
            "tenant_a",
            topics=(("React", "high"),),
            repos=("facebook/react",),
            occupation="frontend engineer",
            interests=("ui",),
        )
        _seed_user(
            connection,
            "tenant_b",
            topics=(("Go", "high"),),
            repos=("golang/go",),
            occupation="backend engineer",
            interests=("apis",),
        )
        alice = load_user_interest(connection, "tenant_a")
        bob = load_user_interest(connection, "tenant_b")

    assert alice.tenant_id == "tenant_a"
    assert bob.tenant_id == "tenant_b"
    assert {concept.concept_id for concept in alice.explicit_concepts()} >= {"react"}
    assert {concept.concept_id for concept in bob.explicit_concepts()} >= {"go"}
    assert "go" not in {concept.concept_id for concept in alice.explicit_concepts()}
    assert "react" not in {concept.concept_id for concept in bob.explicit_concepts()}

    reset = reset_user_interest("tenant_a")
    assert reset.user_id == "tenant_a"
    assert reset.concepts == ()
    assert reset.signal_fingerprint == empty_user_interest("tenant_a").signal_fingerprint

    with database.connect() as connection:
        connection.execute("DELETE FROM topics WHERE user_id = 'tenant_a'")
        connection.execute("DELETE FROM github_repo_watches WHERE user_id = 'tenant_a'")
        connection.execute("DELETE FROM profiles WHERE user_id = 'tenant_a'")
        cleared = load_user_interest(connection, "tenant_a")
        leftover = load_user_interest(connection, "tenant_b")
    assert cleared.concepts == ()
    assert leftover.explicit_concepts()


def test_semantic_neighbors_match_without_string_equality() -> None:
    state = _state("user_compiler", topics=(("compiler optimization", "high"),))
    neighbor = semantic_match(state, "LLVM Scalar Evolution now folds more addrecs.")
    exact = semantic_match(state, "Notes on compiler optimization for loops.")

    assert neighbor.matched
    assert exact.matched
    assert any(hit.match_kind == "neighbor" for hit in neighbor.hits)
    assert "llvm-scalar-evolution" in {hit.concept_id for hit in neighbor.hits}
    assert "compiler optimization" not in "LLVM Scalar Evolution now folds more addrecs.".casefold()


def test_rust_interest_neighbors_crates_registry_without_package_name() -> None:
    rust = _state("u_rust", topics=(("Rust", "high"),))
    match = semantic_match(rust, "chrono 0.4.43 release metadata from crates")

    assert match.matched
    assert any(hit.concept_id == "crates-io" and hit.match_kind == "neighbor" for hit in match.hits)


def test_hard_negatives_do_not_explode_recall() -> None:
    react = _state("u_react", topics=(("React", "high"),))
    java = _state("u_java", topics=(("Java", "high"),))
    golang = _state("u_go", topics=(("Go", "high"),))
    rust = _state("u_rust", topics=(("Rust", "high"),))
    swift = _state("u_swift", topics=(("Swift", "high"),))
    rails = _state("u_rails", topics=(("Rails", "high"),))

    assert semantic_match(react, "facebook/react tagged v19.1.0 with compiler fixes.").matched
    assert not semantic_match(
        react, "An IAEA feed notes a scheduled reactor containment inspection."
    ).matched
    assert not semantic_match(
        react, "reactor/reactor-core tagged 3.7.0 for the Java reactive library."
    ).matched
    assert not semantic_match(react, "How to react during an incident under load.").matched
    assert not semantic_match(react, "ReactOS, the Windows-compatible OS, tagged 0.4.15.").matched

    assert semantic_match(java, "OpenJDK 21.0.6 released with security fixes.").matched
    assert not semantic_match(
        java, "A geology RSS feed reports aftershocks on the island of Java."
    ).matched

    assert semantic_match(golang, "golang/go tagged 1.24.1 with runtime and crypto fixes.").matched
    assert not semantic_match(golang, "Niantic Status: Pokémon GO live map tiles are failing.").matched

    assert semantic_match(rust, "rust-lang/rust tagged 1.82.0 with cargo updates.").matched
    assert not semantic_match(
        rust, "A hardware feed explains rust conversion coatings for iron fences."
    ).matched

    assert semantic_match(swift, "apple/swift tagged 6.1 with typed throws refinements.").matched
    assert not semantic_match(
        swift, "A payments advisory describes a SWIFT network settlement delay."
    ).matched

    assert semantic_match(rails, "rails/rails tagged 8.0.2 with Active Job fixes.").matched
    assert not semantic_match(
        rails, "A transit feed covers steel railway rails being replaced downtown."
    ).matched

    assert "react" not in detect_concepts_in_text("nuclear reactor inspection")
    assert "go" not in detect_concepts_in_text("Pokémon GO map outage")
    assert "java" not in detect_concepts_in_text("island of Java earthquake")


def test_neighbor_aware_matcher_beats_exact_string_on_personalization_gold() -> None:
    corpus = load_personalization_gold(_V01).for_split("pilot")
    items = corpus.item_by_id()
    exact_rankings: dict[str, list[str]] = {}
    semantic_rankings: dict[str, list[str]] = {}

    for user in corpus.users:
        state = state_from_personalization_user(
            user.user_id,
            occupation=user.profile.occupation,
            interests=user.profile.interests,
            topics=tuple((topic.name, topic.priority) for topic in user.topics),
            repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
            prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
        )
        exact_terms = {
            token
            for part in (
                user.profile.occupation,
                *user.profile.interests,
                *(topic.name for topic in user.topics),
                *(repo.full_name for repo in user.repositories),
                *user.products,
            )
            for token in re.findall(r"[a-z0-9.+-]+", part.lower())
            if token
        }
        exact_scored: list[tuple[int, str]] = []
        semantic_scored: list[tuple[float, str]] = []
        for judgment in corpus.judgments_for_user(user.user_id):
            item = items[judgment.item_id]
            blob = f"{item.title} {item.summary} {' '.join(item.tokens)}"
            text = blob.lower()
            tokens = set(re.findall(r"[a-z0-9.+-]+", blob.lower()))
            exact_score = 0
            for term in exact_terms:
                if term in text or any(term in token or token in term for token in tokens):
                    exact_score += 1
            exact_scored.append((exact_score, item.item_id))
            semantic_scored.append((semantic_match(state, blob).score, item.item_id))
        exact_scored.sort(key=lambda pair: (-pair[0], pair[1]))
        semantic_scored.sort(key=lambda pair: (-pair[0], pair[1]))
        exact_rankings[user.user_id] = [item_id for _score, item_id in exact_scored]
        semantic_rankings[user.user_id] = [item_id for _score, item_id in semantic_scored]

    exact = evaluate_personalization(corpus, exact_rankings, k=5, split="pilot")
    semantic = evaluate_personalization(corpus, semantic_rankings, k=5, split="pilot")

    assert semantic.include_ambiguous.precision_at_k > exact.include_ambiguous.precision_at_k
    assert semantic.include_ambiguous.recall_at_k > exact.include_ambiguous.recall_at_k

    react_user = next(
        user.user_id
        for user in corpus.users
        if any(topic.name == "React" for topic in user.topics) and user.kind == "history_rich"
    )
    hard_ids = {
        row.item_id
        for row in corpus.judgments
        if row.user_id == react_user and row.hard_negative
    }
    assert hard_ids
    assert hard_ids & set(exact_rankings[react_user][:3])
    assert not hard_ids & set(semantic_rankings[react_user][:3])

    neighbor_hits = 0
    exact_neighbor_hits = 0
    neighbor_total = 0
    for judgment in corpus.judgments:
        if not judgment.should_surface or judgment.hard_negative:
            continue
        user = corpus.user_by_id()[judgment.user_id]
        item = items[judgment.item_id]
        topic_names = {topic.name.casefold() for topic in user.topics}
        if item.product.casefold() in topic_names:
            continue
        neighbor_total += 1
        blob = f"{item.title} {item.summary}".casefold()
        if any(name and name in blob for name in topic_names):
            exact_neighbor_hits += 1
        state = state_from_personalization_user(
            user.user_id,
            occupation=user.profile.occupation,
            interests=user.profile.interests,
            topics=tuple((topic.name, topic.priority) for topic in user.topics),
            repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
            prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
        )
        if semantic_match(state, f"{item.title} {item.summary}").matched:
            neighbor_hits += 1
    assert neighbor_total
    assert neighbor_hits > exact_neighbor_hits


def _world_ledger_snapshot(database: Database) -> dict[str, object]:
    with database.connect() as connection:
        observations = list(
            connection.execute(
                "SELECT id, payload_hash FROM observations ORDER BY id"
            ).fetchall()
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
                "id": "inc_interest_ledger",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_interest_ledger",
                "incident_updates": [
                    {
                        "id": "upd_interest_ledger",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "display_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def test_user_interest_rebuild_does_not_change_event_claim_ledger(tmp_path: Path) -> None:
    clean = Database(tmp_path / "interest-clean.db")
    clean.initialize()
    noisy = Database(tmp_path / "interest-noisy.db")
    noisy.initialize()

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
            "interest_user",
            topics=(("React", "high"),),
            repos=("facebook/react",),
            occupation="frontend engineer",
            interests=("ui",),
        )
        state = load_user_interest(connection, "interest_user")
        match = semantic_match(state, "React 19.1.0 released")
        rebuilt = load_user_interest(connection, "interest_user")
    after = _world_ledger_snapshot(noisy)
    clean_snapshot = _world_ledger_snapshot(clean)

    assert match.matched
    assert rebuilt.signal_fingerprint == state.signal_fingerprint
    assert before == after
    assert after == clean_snapshot
    assert after["observation_count"] == 1
    assert after["claim_count"] >= 1
    assert after["event_count"] >= 1


def test_japanese_interests_remain_active_concepts() -> None:
    state = _state(
        "user_ja",
        topics=(("コンパイラ最適化", "high"), ("セキュリティ", "normal")),
        interests=("Rust コンパイラ",),
    )
    active = {concept.concept_id: concept for concept in state.active_concepts()}
    assert "compiler-optimization" in active
    assert "security" in active
    assert "rust" in active
    assert any(source.raw_text == "Rust コンパイラ" for source in active["rust"].sources)
    assert any(source.raw_text == "セキュリティ" for source in active["security"].sources)
    assert any(source.raw_text == "コンパイラ最適化" for source in active["compiler-optimization"].sources)


def test_japanese_interest_matches_japanese_and_english_events() -> None:
    state = _state(
        "user_ja_match",
        topics=(("コンパイラ最適化", "high"),),
        interests=("セキュリティ", "Rust コンパイラ"),
    )
    assert semantic_match(state, "コンパイラ最適化の新しいパスを追加した").matched
    assert semantic_match(state, "Notes on compiler optimization for loops.").matched
    assert semantic_match(state, "セキュリティアドバイザリを公開した").matched
    assert semantic_match(state, "Critical security advisory for the package").matched
    assert semantic_match(state, "rust-lang/rust tagged 1.82.0 with cargo updates.").matched
    assert semantic_match(state, "Rust コンパイラのコード生成を修正").matched
