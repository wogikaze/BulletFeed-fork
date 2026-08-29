from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.database import Database
from app.db.migrations import KNOWN_REVISIONS
from app.evaluation.personalization_gold import (
    PersonalizationGoldCorpus,
    evaluate_personalization,
    load_personalization_gold,
)
from app.services.feedback_signals import (
    assert_feedback_does_not_mutate_ledger,
    ledger_world_state,
)
from app.services.offline_preference import (
    DECAY_HALF_LIFE_SECONDS,
    MIN_EVIDENCE,
    POLICY_VERSION,
    SIGNAL_WEIGHTS,
    TRAINING_SCHEMA_VERSION,
    TrainingBatch,
    TrainingExample,
    decay_factor,
    documented_decay_half_life_seconds,
    documented_signal_weights,
    inspect_user_preference,
    preference_overlay,
    score_with_preference,
    train_preference,
    validate_training_batch,
)
from app.services.ranking import evaluate_importance
from app.services.ranking_feedback import (
    PERSONALIZATION_VERSION,
    apply_feedback_ranking,
    reset_feedback_ranking,
)
from app.services.user_interest import (
    detect_concepts_in_text,
    semantic_match,
    state_from_personalization_user,
)

_V01 = Path(__file__).parent / "gold" / "personalization" / "v01"


def _example(
    *,
    user_id: str = "learner",
    feed_item_id: str,
    feedback_type: str,
    created_at: int,
    feature_kind: str = "source_type",
    feature_value: str = "github_release",
    split: str = "train",
) -> TrainingExample:
    return TrainingExample(
        user_id=user_id,
        feed_item_id=feed_item_id,
        feedback_type=feedback_type,
        created_at=created_at,
        feature_kind=feature_kind,
        feature_value=feature_value,
        split=split,
    )


def _batch(user_id: str, examples: list[TrainingExample]) -> TrainingBatch:
    return TrainingBatch(
        schema_version=TRAINING_SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        user_id=user_id,
        examples=examples,
    )


def _insert_item(
    connection,
    *,
    user_id: str,
    item_id: str,
    event_id: str,
    source_type: str,
    updated_at: str,
    title: str | None = None,
    summary: str = "",
    delta_type: str = "detail",
) -> None:
    connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)", (user_id,))
    event_title = title or f"{source_type} {event_id}"
    connection.execute(
        """
        INSERT INTO events (
            id, title, summary, current_phase, current_summary,
            current_since, current_confidence, updated_at
        ) VALUES (?, ?, ?, 'published', '', ?, 'high', ?)
        """,
        (event_id, event_title, summary, updated_at, updated_at),
    )
    connection.execute(
        """
        INSERT INTO ledger_events (
            id, source_type, source_key, source_event_id, title, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_id, source_type, event_id, event_id, event_title, updated_at),
    )
    delta_id = f"d_{item_id}"
    connection.execute(
        """
        INSERT INTO deltas (
            id, event_id, type, summary, before_text, after_text, occurred_at
        ) VALUES (?, ?, ?, '', '', '', ?)
        """,
        (delta_id, event_id, delta_type, updated_at),
    )
    importance = evaluate_importance(source_type=source_type, delta_type=delta_type)
    connection.execute(
        """
        INSERT INTO feed_items (
            id, user_id, event_id, delta_id, title,
            importance_level, importance_reason, importance_confidence,
            relation_level, relation_reason, matched_topics_json,
            matched_repos_json, personalization_rank,
            status, dismissed, marked_important, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reference', '', '[]', '[]', 0, 'unread', 0, 0, ?)
        """,
        (
            item_id,
            user_id,
            event_id,
            delta_id,
            event_title,
            importance.level,
            importance.reason,
            importance.confidence,
            updated_at,
        ),
    )


def _mark(connection, *, user_id: str, item_id: str, feedback_type: str, created_at: int) -> None:
    connection.execute(
        """
        INSERT INTO feedback (id, feed_item_id, user_id, type, created_at, family, superseded)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (
            f"fb_{item_id}_{feedback_type}_{created_at}",
            item_id,
            user_id,
            feedback_type,
            created_at,
            {
                "important": "ranking",
                "not_relevant": "ranking",
                "already_knew": "knowledge",
                "learned_now": "knowledge",
                "follow": "follow",
                "less_like_this": "preference",
            }[feedback_type],
        ),
    )


def _ordered_ids(connection, user_id: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT id, importance_level, relation_level, personalization_rank, updated_at
        FROM feed_items
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    rel = {"direct": 3, "adjacent": 2, "reference": 1}
    return [
        row["id"]
        for row in sorted(
            rows,
            key=lambda row: (
                rank[row["importance_level"]],
                rel[row["relation_level"]],
                int(row["personalization_rank"]),
                row["updated_at"],
                row["id"],
            ),
            reverse=True,
        )
    ]


def _held_out_fixture(database: Database) -> None:
    with database.connect() as connection:
        for index in range(MIN_EVIDENCE):
            _insert_item(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                event_id=f"ev_train_{index}",
                source_type="github_release",
                updated_at=f"2026-08-20T00:0{index}:00Z",
                title=f"React patch {index}",
                summary="facebook/react tagged a compiler fix.",
            )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_release",
            event_id="ev_held_release",
            source_type="github_release",
            updated_at="2026-08-21T00:00:00Z",
            title="React 19.2.0 released",
            summary="facebook/react tagged v19.2.0.",
        )
        _insert_item(
            connection,
            user_id="learner",
            item_id="held_rss",
            event_id="ev_held_rss",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            title="Unrelated rust blog",
            summary="A rustc internals essay.",
            delta_type="new_fact",
        )
        _insert_item(
            connection,
            user_id="other",
            item_id="other_release",
            event_id="ev_other_release",
            source_type="github_release",
            updated_at="2026-08-21T00:00:00Z",
            title="Other user release",
        )


def test_training_schema_is_versioned_and_rejects_blind_labels() -> None:
    assert TRAINING_SCHEMA_VERSION == "preference-training-v1"
    assert POLICY_VERSION == "offline-preference-v1"
    with pytest.raises(ValidationError):
        TrainingExample.model_validate(
            {
                "user_id": "learner",
                "feed_item_id": "item",
                "feedback_type": "important",
                "created_at": 1,
                "feature_kind": "source_type",
                "feature_value": "github_release",
                "split": "blind",
            }
        )
    with pytest.raises(ValidationError):
        TrainingBatch(
            schema_version="preference-training-v0",
            policy_version=POLICY_VERSION,
            user_id="learner",
            examples=[],
        )
    parsed = validate_training_batch(
        {
            "schema_version": TRAINING_SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "user_id": "learner",
            "examples": [],
        }
    )
    assert parsed.schema_version == TRAINING_SCHEMA_VERSION
    assert all(example.split != "blind" for example in parsed.examples)


def test_signal_weights_and_decay_are_documented() -> None:
    weights = documented_signal_weights()
    assert weights == SIGNAL_WEIGHTS
    assert weights["important"] > 0
    assert weights["follow"] > 0
    assert weights["learned_now"] > 0
    assert weights["already_knew"] > 0
    assert weights["already_knew"] < weights["learned_now"] < weights["follow"] < weights["important"]
    assert weights["not_relevant"] < 0
    assert weights["less_like_this"] < 0
    assert documented_decay_half_life_seconds() == DECAY_HALF_LIFE_SECONDS
    assert decay_factor(0, 0) == 1.0
    assert decay_factor(0, DECAY_HALF_LIFE_SECONDS) == pytest.approx(0.5)


def test_one_click_does_not_overfit() -> None:
    state = train_preference(
        _batch(
            "learner",
            [_example(feed_item_id="only", feedback_type="important", created_at=10)],
        )
    )
    assert state.is_sparse()
    assert state.evidence_count == 1
    assert all(item.weight == 0 for item in state.weights)
    overlay = preference_overlay(
        state,
        source_type="github_release",
        text="React 19",
        has_explicit_authority=False,
    )
    assert overlay.applied is False
    assert overlay.rank_delta == 0


def test_replay_is_deterministic_and_inspectable() -> None:
    examples = [
        _example(feed_item_id=f"t{index}", feedback_type="follow", created_at=20 + index)
        for index in range(MIN_EVIDENCE)
    ]
    first = train_preference(_batch("learner", examples))
    second = train_preference(_batch("learner", examples))
    assert first == second
    assert first.fingerprint == second.fingerprint
    assert first.policy_version == POLICY_VERSION
    assert first.schema_version == TRAINING_SCHEMA_VERSION
    source = first.weight_map()[("source_type", "github_release")]
    assert source.evidence_count == MIN_EVIDENCE
    assert source.weight > 0
    assert first.inspect() == first.weights


def test_sparse_history_is_a_regression_guard() -> None:
    examples = [
        _example(user_id="sparse", feed_item_id="a", feedback_type="important", created_at=1),
        _example(user_id="sparse", feed_item_id="b", feedback_type="not_relevant", created_at=2),
    ]
    state = train_preference(_batch("sparse", examples))
    assert state.is_sparse()
    before = 0.42
    after = score_with_preference(
        state,
        source_type="github_release",
        text="React 19",
        baseline=before,
    )
    assert after == before


def test_explicit_authority_caps_weak_implicit_signals() -> None:
    examples = [
        _example(
            feed_item_id=f"knew_{index}",
            feedback_type="already_knew",
            created_at=30 + index,
        )
        for index in range(MIN_EVIDENCE)
    ]
    state = train_preference(_batch("learner", examples))
    implicit = preference_overlay(
        state,
        source_type="github_release",
        text="React 19 released",
        has_explicit_authority=False,
    )
    explicit = preference_overlay(
        state,
        source_type="github_release",
        text="React 19 released",
        has_explicit_authority=True,
    )
    assert implicit.applied and explicit.applied
    assert abs(explicit.rank_delta) <= abs(implicit.rank_delta)
    assert abs(explicit.rank_delta) <= 20
    assert POLICY_VERSION in explicit.debug
    important = train_preference(
        _batch(
            "learner",
            [
                _example(
                    feed_item_id=f"imp_{index}",
                    feedback_type="important",
                    created_at=40 + index,
                )
                for index in range(MIN_EVIDENCE)
            ],
        )
    )
    weak = state.weight_map()[("source_type", "github_release")].weight
    strong = important.weight_map()[("source_type", "github_release")].weight
    assert weak < strong


def test_follow_batch_changes_held_out_order_with_policy_version(database: Database) -> None:
    _held_out_fixture(database)
    with database.connect() as connection:
        before = _ordered_ids(connection, "learner")
        assert before.index("held_rss") < before.index("held_release")
        for index in range(MIN_EVIDENCE):
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                feedback_type="follow",
                created_at=50 + index,
            )
        apply_feedback_ranking(connection, user_id="learner")
        after = _ordered_ids(connection, "learner")
        held = connection.execute(
            "SELECT importance_reason, personalization_rank, importance_level "
            "FROM feed_items WHERE id = 'held_release'"
        ).fetchone()
        other = connection.execute(
            "SELECT importance_reason FROM feed_items WHERE id = 'other_release'"
        ).fetchone()
        model = inspect_user_preference(connection, user_id="learner")

    assert after.index("held_release") < after.index("held_rss")
    assert POLICY_VERSION in held["importance_reason"]
    assert held["personalization_rank"] > 0
    assert POLICY_VERSION not in other["importance_reason"]
    assert model.policy_version == POLICY_VERSION
    assert model.evidence_count >= MIN_EVIDENCE


def test_preference_state_is_per_user_and_resettable(database: Database) -> None:
    _held_out_fixture(database)
    with database.connect() as connection:
        for index in range(MIN_EVIDENCE):
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                feedback_type="less_like_this",
                created_at=60 + index,
            )
        apply_feedback_ranking(connection, user_id="learner")
        apply_feedback_ranking(connection, user_id="other")
        learner = inspect_user_preference(connection, user_id="learner")
        other = inspect_user_preference(connection, user_id="other")
        assert learner.evidence_count >= MIN_EVIDENCE
        assert other.evidence_count == 0
        held_before_reset = connection.execute(
            "SELECT personalization_rank, importance_reason FROM feed_items WHERE id = 'held_release'"
        ).fetchone()
        assert POLICY_VERSION in held_before_reset["importance_reason"]

        reset_feedback_ranking(connection, user_id="learner", reset_at=100)
        restored = inspect_user_preference(connection, user_id="learner")
        held = connection.execute(
            "SELECT personalization_rank, importance_reason FROM feed_items WHERE id = 'held_release'"
        ).fetchone()

    assert restored.evidence_count == 0
    assert restored.weights == ()
    assert POLICY_VERSION not in held["importance_reason"]
    assert PERSONALIZATION_VERSION not in held["importance_reason"]


def test_training_does_not_rewrite_ledger_truth(database: Database) -> None:
    _held_out_fixture(database)
    with database.connect() as connection:
        before = ledger_world_state(connection)
        for index in range(MIN_EVIDENCE):
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                feedback_type="learned_now",
                created_at=70 + index,
            )
        apply_feedback_ranking(connection, user_id="learner")
        after = ledger_world_state(connection)
        assert_feedback_does_not_mutate_ledger(before, after)
        assert after["hashes"] == before["hashes"]
        claims = connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0]
        events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        deltas = connection.execute("SELECT COUNT(*) FROM deltas").fetchone()[0]
        assert claims == before["counts"]["state_claims"]
        assert events == before["counts"]["events"]
        assert deltas == before["counts"]["deltas"]


def test_explicit_topic_outranks_weak_implicit_preference(database: Database) -> None:
    _held_out_fixture(database)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
            VALUES ('topic_react', 'learner', 'React', 'technology', 'high', 0, 0)
            """
        )
        for index in range(MIN_EVIDENCE):
            _mark(
                connection,
                user_id="learner",
                item_id=f"train_{index}",
                feedback_type="already_knew",
                created_at=80 + index,
            )
        apply_feedback_ranking(connection, user_id="learner")
        held = connection.execute(
            """
            SELECT relation_level, personalization_rank, importance_reason, matched_topics_json
            FROM feed_items WHERE id = 'held_release'
            """
        ).fetchone()
        rss = connection.execute(
            "SELECT relation_level, personalization_rank FROM feed_items WHERE id = 'held_rss'"
        ).fetchone()

    assert held["relation_level"] == "adjacent"
    assert "React" in held["matched_topics_json"]
    assert held["personalization_rank"] > rss["personalization_rank"]
    assert POLICY_VERSION in held["importance_reason"]


def _pilot_corpus() -> PersonalizationGoldCorpus:
    return load_personalization_gold(_V01).for_split("pilot")


def _lexical_score(user, item) -> float:
    terms = {
        token
        for blob in (
            user.profile.occupation,
            *user.profile.interests,
            *(topic.name for topic in user.topics),
            *(repo.full_name for repo in user.repositories),
            *user.products,
        )
        for token in blob.casefold().split()
        if token
    }
    text = f"{item.title} {item.summary} {' '.join(item.tokens)}".casefold()
    return float(sum(1 for term in terms if term in text))


def _interest_state(user):
    return state_from_personalization_user(
        user.user_id,
        occupation=user.profile.occupation,
        interests=user.profile.interests,
        topics=tuple((topic.name, topic.priority) for topic in user.topics),
        repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
        prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
    )


def _examples_from_judgments(user, items, judgments) -> list[TrainingExample]:
    examples: list[TrainingExample] = []
    for index, judgment in enumerate(judgments):
        item = items[judgment.item_id]
        if judgment.should_surface:
            feedback_type = "important"
        elif judgment.hard_negative or judgment.relevance == 0:
            feedback_type = "not_relevant"
        else:
            continue
        created_at = 1_000 + index
        text = f"{item.title} {item.summary} {' '.join(item.tokens)}"
        for concept_id in detect_concepts_in_text(text):
            examples.append(
                _example(
                    user_id=user.user_id,
                    feed_item_id=item.item_id,
                    feedback_type=feedback_type,
                    created_at=created_at,
                    feature_kind="concept",
                    feature_value=concept_id,
                )
            )
    return examples


def _subset_corpus(
    corpus: PersonalizationGoldCorpus,
    judgments,
) -> PersonalizationGoldCorpus:
    selected = tuple(judgments)
    user_ids = {row.user_id for row in selected}
    item_ids = {row.item_id for row in selected}
    return PersonalizationGoldCorpus(
        dataset_version=corpus.dataset_version,
        label_protocol_version=corpus.label_protocol_version,
        users=tuple(user for user in corpus.users if user.user_id in user_ids),
        items=tuple(item for item in corpus.items if item.item_id in item_ids),
        judgments=selected,
    )


def test_held_out_gold_compares_precision_and_ndcg_before_after() -> None:
    corpus = _pilot_corpus()
    assert all(user.split == "pilot" for user in corpus.users)
    assert all(item.split == "pilot" for item in corpus.items)
    items = corpus.item_by_id()
    holdout_judgments = []
    before_rankings: dict[str, list[str]] = {}
    after_rankings: dict[str, list[str]] = {}
    sparse_equal = 0

    for user in corpus.users:
        judged = sorted(corpus.judgments_for_user(user.user_id), key=lambda row: row.item_id)
        if len(judged) < 4:
            continue
        split_at = max(MIN_EVIDENCE, len(judged) // 2)
        train_rows = judged[:split_at]
        holdout_rows = judged[split_at:]
        holdout_judgments.extend(holdout_rows)
        examples = _examples_from_judgments(user, items, train_rows)
        state = train_preference(_batch(user.user_id, examples))
        interest = _interest_state(user)
        scored_before: list[tuple[float, str]] = []
        scored_after: list[tuple[float, str]] = []
        for judgment in holdout_rows:
            item = items[judgment.item_id]
            text = f"{item.title} {item.summary} {' '.join(item.tokens)}"
            baseline = _lexical_score(user, item) + semantic_match(interest, text).score
            explicit = any(
                topic.name.casefold() in text.casefold() for topic in user.topics
            ) or any(repo.full_name.casefold() in text.casefold() for repo in user.repositories)
            scored_before.append((baseline, item.item_id))
            scored_after.append(
                (
                    score_with_preference(
                        state,
                        source_type=item.source_family,
                        text=text,
                        baseline=baseline,
                        has_explicit_authority=explicit,
                    ),
                    item.item_id,
                )
            )
        scored_before.sort(key=lambda pair: (-pair[0], pair[1]))
        scored_after.sort(key=lambda pair: (-pair[0], pair[1]))
        before_rankings[user.user_id] = [item_id for _, item_id in scored_before]
        after_rankings[user.user_id] = [item_id for _, item_id in scored_after]
        if user.kind == "cold_start" or state.is_sparse():
            assert before_rankings[user.user_id] == after_rankings[user.user_id]
            sparse_equal += 1

    holdout = _subset_corpus(corpus, holdout_judgments)
    before = evaluate_personalization(holdout, before_rankings, k=5)
    after = evaluate_personalization(holdout, after_rankings, k=5)

    assert before.include_ambiguous.precision_at_k >= 0
    assert after.include_ambiguous.precision_at_k >= before.include_ambiguous.precision_at_k
    assert after.include_ambiguous.ndcg_at_k >= before.include_ambiguous.ndcg_at_k
    assert after.exclude_ambiguous.ndcg_at_k >= before.exclude_ambiguous.ndcg_at_k
    assert sparse_equal >= 1
    assert holdout.users
    assert all(row.split == "pilot" for row in holdout.judgments)


def test_revision_15_adds_preference_tables_without_touching_ledger(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-preference.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '15'")
        connection.execute("DROP TABLE IF EXISTS user_preference_weights")
        connection.execute("DROP TABLE IF EXISTS user_preference_models")
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (
                'obs_pref', 'statuspage', 'abcd1234', 'inc_pref',
                'hash', '{}', 'https://example.test', '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO ledger_events (
                id, source_type, source_key, source_event_id, title, created_at
            ) VALUES (
                'event_pref', 'statuspage', 'abcd1234', 'inc_pref', 'Legacy',
                '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO events (
                id, title, summary, current_phase, current_summary,
                current_since, current_confidence, updated_at
            ) VALUES (
                'event_pref', 'Legacy', '', 'published', '',
                '2026-08-22T00:00:00Z', 'high', '2026-08-22T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO state_claims (
                id, event_id, observation_id, slot, value_text, detail_text,
                valid_at, observed_at
            ) VALUES (
                'claim_pref', 'event_pref', 'obs_pref', 'status', 'investigating', 'Legacy',
                '2026-08-22T00:00:00Z', '2026-08-22T00:00:00Z'
            )
            """
        )
        before_claims = connection.execute("SELECT value_text FROM state_claims").fetchall()

    database.initialize()

    with database.connect() as connection:
        revisions = {
            row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_preference_models'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_preference_weights'"
        ).fetchone()
        after_claims = connection.execute("SELECT value_text FROM state_claims").fetchall()
        assert after_claims == before_claims
        assert connection.execute("SELECT COUNT(*) FROM user_preference_models").fetchone()[0] == 0
