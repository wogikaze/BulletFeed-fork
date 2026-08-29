from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.personalization_gold import (
    evaluate_personalization,
    load_personalization_gold,
)
from app.services.event_concepts import extract_event_concepts
from app.services.relation import (
    RELATION_FEATURE_VERSION,
    consume_concept_features,
    evaluate_relation,
    evaluate_relation_from_state,
)
from app.services.user_interest import (
    InterestSources,
    rebuild_user_interest,
    signals_from_sources,
    state_from_personalization_user,
)

_V01 = Path(__file__).parent / "gold" / "personalization" / "v01"
_LEVEL_ORDER = {"direct": 3, "adjacent": 2, "reference": 1}


def _state(
    user_id: str,
    *,
    topics: tuple[tuple[str, str], ...] = (),
    repositories: tuple[tuple[str, str], ...] = (),
    occupation: str = "",
    interests: tuple[str, ...] = (),
    inferred: tuple[str, ...] = (),
    feedback: tuple[tuple[str, str], ...] = (),
):
    return rebuild_user_interest(
        user_id,
        signals_from_sources(
            InterestSources(
                topics=topics,
                repositories=repositories,
                occupation=occupation,
                profile_interests=interests,
                inferred_technologies=inferred,
                feedback=feedback,
            )
        ),
    )


def _score(
    state,
    *,
    title: str,
    summary: str = "",
    source_type: str = "rss_atom",
    source_key: str = "https://example.test/feed.xml",
):
    return evaluate_relation_from_state(
        state,
        source_type=source_type,
        source_key=source_key,
        event_title=title,
        event_summary=summary,
    )


def _seed_user(connection, user_id: str, *, topics=(), repos=(), occupation="", interests=()) -> None:
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


def test_relation_feature_version_is_replayable() -> None:
    assert RELATION_FEATURE_VERSION
    assert RELATION_FEATURE_VERSION.startswith("relation-features-")
    first = _score(_state("u", topics=(("Kotlin", "high"),)), title="Kotlin 2.3 migration guide")
    second = _score(_state("u", topics=(("Kotlin", "high"),)), title="Kotlin 2.3 migration guide")
    assert first.feature_version == RELATION_FEATURE_VERSION
    assert first == second


def test_direct_selected_repository_remains_deterministic(database) -> None:
    with database.connect() as connection:
        _seed_user(connection, "owner", repos=("facebook/react",))
        _seed_user(connection, "other", repos=("golang/go",))
        direct = evaluate_relation(
            connection,
            user_id="owner",
            source_type="github_release",
            source_key="facebook/react",
            event_title="Unrelated kitchen notes",
            event_summary="No concept overlap required.",
        )
        isolated = evaluate_relation(
            connection,
            user_id="other",
            source_type="github_release",
            source_key="facebook/react",
            event_title="React 19.1.0 released",
            event_summary="Compiler fixes.",
        )

    assert direct.level == "direct"
    assert direct.personalization_rank == 1000
    assert direct.matched_repositories[0]["name"] == "facebook/react"
    assert RELATION_FEATURE_VERSION in direct.reason
    assert isolated.level != "direct"
    assert isolated.matched_repositories == ()


def test_semantic_overlap_without_exact_topic_string() -> None:
    state = _state("compiler", topics=(("compiler optimization", "high"),))
    adjacent = _score(state, title="LLVM Scalar Evolution now folds more addrecs.")
    assert adjacent.level == "adjacent"
    assert adjacent.score > 0
    assert "compiler optimization" not in "LLVM Scalar Evolution now folds more addrecs.".casefold()
    assert any(token in adjacent.reason.lower() for token in ("llvm", "scalar", "neighbor"))
    assert RELATION_FEATURE_VERSION in adjacent.reason


def test_hard_negatives_stay_reference_not_adjacent() -> None:
    react = _state("u_react", topics=(("React", "high"),), repositories=(("facebook/react", "JavaScript"),))
    java = _state("u_java", topics=(("Java", "high"),))
    golang = _state("u_go", topics=(("Go", "high"),))

    assert _score(react, title="facebook/react tagged v19.1.0 with compiler fixes.").level == "adjacent"
    assert (
        _score(
            react,
            title="IAEA nuclear reactor inspection briefing",
            summary="Scheduled reactor containment inspection.",
        ).level
        == "reference"
    )
    assert (
        _score(
            react,
            title="Project Reactor 3.7.0 released",
            summary="reactor/reactor-core tagged 3.7.0 for the Java reactive library.",
            source_type="github_release",
            source_key="reactor/reactor-core",
        ).level
        == "reference"
    )
    assert (
        _score(react, title="How to react during an incident under load.").level == "reference"
    )

    assert _score(java, title="OpenJDK 21.0.6 released with security fixes.").level == "adjacent"
    assert (
        _score(
            java,
            title="Java island earthquake status",
            summary="Aftershocks continue on the island of Java.",
        ).level
        == "reference"
    )

    assert (
        _score(
            golang,
            title="golang/go tagged 1.24.1",
            summary="Runtime and crypto fixes.",
            source_type="github_release",
            source_key="golang/go",
        ).level
        in {"direct", "adjacent"}
    )
    assert (
        _score(
            golang,
            title="Pokémon GO map outage",
            summary="Niantic Status: Pokémon GO live map tiles are failing.",
        ).level
        == "reference"
    )


def test_missing_concepts_are_conservative_reference() -> None:
    state = _state("emptyish", topics=(("React", "high"),))
    blank = _score(state, title="   ", summary="")
    noise = _score(state, title="Office kitchen notes", summary="The espresso machine is back online.")
    assert blank.level == "reference"
    assert blank.score == 0
    assert blank.matched_topics == ()
    assert noise.level == "reference"


def test_explicit_interest_outranks_inferred_overlap() -> None:
    state = _state(
        "mixed",
        topics=(("React", "high"),),
        repositories=(("facebook/react", "JavaScript"),),
    )
    explicit = _score(state, title="React 19.1.0 released", summary="Compiler fixes for facebook/react.")
    inferred = _score(state, title="JavaScript Weekly issue 900", summary="Language trivia.")
    both = _score(
        state,
        title="React 19 ships with JavaScript compiler notes",
        summary="facebook/react release.",
    )

    assert explicit.level == "adjacent"
    assert inferred.level == "adjacent"
    assert explicit.personalization_rank > inferred.personalization_rank
    assert both.personalization_rank >= explicit.personalization_rank
    assert "explicit" in both.reason
    assert both.score > 0


def test_feedback_alone_does_not_create_adjacent_relation() -> None:
    state = _state(
        "feedback_only",
        feedback=(("github_release ev_train_0", "important"),),
    )
    signal = _score(
        state,
        title="github_release ev_held_release",
        source_type="github_release",
        source_key="ev_held_release",
    )
    assert signal.level == "reference"
    assert signal.matched_topics == ()


def test_consume_concept_features_without_reparsing_prose() -> None:
    extraction = extract_event_concepts(
        {
            "event_id": "evt-relation",
            "source_type": "github_release",
            "source_key": "facebook/react",
            "title": "React 19.1.0 released",
            "summary": "Compiler fixes for facebook/react.",
        }
    )
    terms = consume_concept_features(extraction.features_for_relation())
    assert "React" in terms
    assert "repo:facebook/react" in terms
    snapshot = extraction.features_for_relation().to_snapshot()
    assert "title" not in snapshot
    assert consume_concept_features(snapshot) == terms


def test_tenant_isolation_does_not_leak_topics(database) -> None:
    with database.connect() as connection:
        _seed_user(connection, "alice", topics=(("React", "high"),))
        _seed_user(connection, "bob", topics=(("Go", "high"),))
        alice = evaluate_relation(
            connection,
            user_id="alice",
            source_type="rss_atom",
            source_key="https://eng.example/feed.xml",
            event_title="React 19.1.0 released",
            event_summary="Compiler fixes.",
        )
        bob = evaluate_relation(
            connection,
            user_id="bob",
            source_type="rss_atom",
            source_key="https://eng.example/feed.xml",
            event_title="React 19.1.0 released",
            event_summary="Compiler fixes.",
        )
        bob_go = evaluate_relation(
            connection,
            user_id="bob",
            source_type="rss_atom",
            source_key="https://eng.example/feed.xml",
            event_title="Go 1.24.1 runtime fixes",
            event_summary="The Go compiler and runtime shipped a patch.",
        )

    assert alice.level == "adjacent"
    assert "React" in alice.matched_topics
    assert bob.level == "reference"
    assert bob.matched_topics == ()
    assert bob_go.level == "adjacent"
    assert any("go" in topic.casefold() for topic in bob_go.matched_topics)


def _relation_rankings(corpus) -> dict[str, list[str]]:
    items = corpus.item_by_id()
    rankings: dict[str, list[str]] = {}
    for user in corpus.users:
        state = state_from_personalization_user(
            user.user_id,
            occupation=user.profile.occupation,
            interests=user.profile.interests,
            topics=tuple((topic.name, topic.priority) for topic in user.topics),
            repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
            prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
        )
        scored: list[tuple[int, int, float, str]] = []
        for judgment in corpus.judgments_for_user(user.user_id):
            item = items[judgment.item_id]
            signal = evaluate_relation_from_state(
                state,
                source_type=item.source_family,
                source_key=item.publisher,
                event_title=item.title,
                event_summary=item.summary,
            )
            scored.append(
                (
                    _LEVEL_ORDER[signal.level],
                    signal.personalization_rank,
                    signal.score,
                    item.item_id,
                )
            )
        scored.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))
        rankings[user.user_id] = [item_id for _level, _rank, _score, item_id in scored]
    return rankings


def _lexical_rankings(corpus) -> dict[str, list[str]]:
    items = corpus.item_by_id()
    rankings: dict[str, list[str]] = {}
    for user in corpus.users:
        terms = {
            token
            for part in (
                user.profile.occupation,
                *user.profile.interests,
                *(topic.name for topic in user.topics),
                *(repo.full_name for repo in user.repositories),
                *user.products,
            )
            for token in part.lower().replace("/", " ").split()
            if token
        }
        scored: list[tuple[int, str]] = []
        for judgment in corpus.judgments_for_user(user.user_id):
            item = items[judgment.item_id]
            blob = f"{item.title} {item.summary} {' '.join(item.tokens)}".lower()
            score = sum(1 for term in terms if term in blob)
            scored.append((score, item.item_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        rankings[user.user_id] = [item_id for _score, item_id in scored]
    return rankings


def _false_positive_rate(corpus, rankings: dict[str, list[str]], *, k: int) -> float:
    rates: list[float] = []
    for user in corpus.users:
        judged = {row.item_id: row for row in corpus.judgments_for_user(user.user_id)}
        top = [item_id for item_id in rankings.get(user.user_id, ()) if item_id in judged][:k]
        if not top:
            continue
        false_hits = sum(1 for item_id in top if not judged[item_id].should_surface)
        rates.append(false_hits / len(top))
    return sum(rates) / len(rates) if rates else 0.0


def test_semantic_relation_does_not_ace_gold_via_hard_negatives() -> None:
    corpus = load_personalization_gold(_V01).for_split("pilot")
    items = corpus.item_by_id()
    relation_rankings = _relation_rankings(corpus)
    lexical = evaluate_personalization(corpus, _lexical_rankings(corpus), k=5, split="pilot")
    semantic = evaluate_personalization(corpus, relation_rankings, k=5, split="pilot")
    fpr = _false_positive_rate(corpus, relation_rankings, k=5)

    react_user = next(
        user.user_id
        for user in corpus.users
        if "react" in user.products and user.kind == "history_rich"
    )
    hard_ids = {
        row.item_id for row in corpus.judgments if row.user_id == react_user and row.hard_negative
    }
    assert hard_ids
    assert not hard_ids & set(relation_rankings[react_user][:3])

    adjacent_or_direct = 0
    hard_promoted = 0
    judged = 0
    for user in corpus.users:
        state = state_from_personalization_user(
            user.user_id,
            occupation=user.profile.occupation,
            interests=user.profile.interests,
            topics=tuple((topic.name, topic.priority) for topic in user.topics),
            repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
            prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
        )
        for judgment in corpus.judgments_for_user(user.user_id):
            judged += 1
            item = items[judgment.item_id]
            signal = evaluate_relation_from_state(
                state,
                source_type=item.source_family,
                source_key=item.publisher,
                event_title=item.title,
                event_summary=item.summary,
            )
            if signal.level in {"adjacent", "direct"}:
                adjacent_or_direct += 1
                if judgment.hard_negative:
                    hard_promoted += 1

    assert hard_promoted == 0
    assert adjacent_or_direct / judged < 0.85
    assert semantic.include_ambiguous.precision_at_k > 0
    assert semantic.include_ambiguous.recall_at_k > 0
    assert semantic.include_ambiguous.precision_at_k >= lexical.include_ambiguous.precision_at_k
    assert semantic.include_ambiguous.precision_at_k < 0.80
    assert 0.0 <= fpr <= 1.0


def test_blind_relevance_reports_precision_recall_and_false_positive_rate() -> None:
    corpus = load_personalization_gold(_V01).for_split("blind")
    rankings = _relation_rankings(corpus)
    report = evaluate_personalization(corpus, rankings, k=5, split="blind")
    fpr = _false_positive_rate(corpus, rankings, k=5)

    assert report.split == "blind"
    assert 0.0 <= report.include_ambiguous.precision_at_k <= 1.0
    assert 0.0 <= report.include_ambiguous.recall_at_k <= 1.0
    assert 0.0 <= fpr <= 1.0
    assert report.include_ambiguous.user_count == len(corpus.users)
