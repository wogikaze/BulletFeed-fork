from __future__ import annotations

import json
import sqlite3
import time
from typing import Literal

from app.services.feedback_signals import RANKING_FEATURE_TYPES
from app.services.offline_preference import (
    FEATURE_KIND_CONCEPT,
    UserPreferenceState,
    preference_overlay,
    reset_user_preference,
    train_and_persist_user_preference,
)
from app.services.ranking import evaluate_importance
from app.services.relation import evaluate_relation
from app.services.user_interest import detect_concepts_in_text

MIN_SAMPLE_SIZE = 3
FEATURE_KIND_SOURCE_TYPE = "source_type"
PERSONALIZATION_VERSION = "ranking-feedback-v0"
RANK_BONUS = 50

_IMPORTANCE_ORDER = ("low", "medium", "high", "critical")
_RELATION_ORDER = ("reference", "adjacent", "direct")
Adjustment = Literal["boost_importance", "demote_relation"]


def apply_feedback_ranking(connection: sqlite3.Connection, *, user_id: str) -> int:
    """Rebuild per-user features from feedback, then overlay ranks only.

    Baseline importance/relation still come from evaluate_importance /
    evaluate_relation. Feedback never enters those functions or judge_revision.
    Learned preference weights are a deterministic batch rebuild.
    """
    rebuild_user_ranking_features(connection, user_id=user_id)
    preference = train_and_persist_user_preference(
        connection,
        user_id=user_id,
        reset_at=_reset_at(connection, user_id),
    )
    return _apply_adjustments(connection, user_id=user_id, preference=preference)


def reset_feedback_ranking(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    reset_at: int | None = None,
) -> int:
    """Forget learned ranking features for one user and restore baseline ranks.

    Returns the cutoff written to user_ranking_resets. Feedback rows stay;
    rebuilds ignore rows at or before this timestamp.
    """
    at = int(time.time()) if reset_at is None else reset_at
    connection.execute(
        """
        INSERT INTO user_ranking_resets (user_id, reset_at) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET reset_at = excluded.reset_at
        """,
        (user_id, at),
    )
    reset_user_preference(connection, user_id=user_id)
    apply_feedback_ranking(connection, user_id=user_id)
    return at


def rebuild_user_ranking_features(connection: sqlite3.Connection, *, user_id: str) -> None:
    reset_at = _reset_at(connection, user_id)
    connection.execute("DELETE FROM user_ranking_features WHERE user_id = ?", (user_id,))
    rows = connection.execute(
        """
        SELECT
            fb.type AS feedback_type,
            COALESCE(le.source_type, 'unknown') AS source_type,
            e.title AS title,
            e.summary AS summary
        FROM (
            SELECT
                user_id,
                feed_item_id,
                type,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id, feed_item_id, COALESCE(
                        family,
                        CASE type
                            WHEN 'important' THEN 'ranking'
                            WHEN 'not_relevant' THEN 'ranking'
                            WHEN 'already_knew' THEN 'knowledge'
                            WHEN 'learned_now' THEN 'knowledge'
                            WHEN 'follow' THEN 'follow'
                            WHEN 'less_like_this' THEN 'preference'
                            ELSE type
                        END
                    )
                    ORDER BY created_at DESC, id DESC
                ) AS rn
            FROM feedback
            WHERE user_id = ? AND created_at > ?
        ) fb
        JOIN feed_items f ON f.id = fb.feed_item_id AND f.user_id = fb.user_id
        LEFT JOIN ledger_events le ON le.id = f.event_id
        LEFT JOIN events e ON e.id = f.event_id
        WHERE fb.rn = 1 AND fb.type != 'undo'
        """,
        (user_id, reset_at),
    ).fetchall()
    source_tallies: dict[str, dict[str, int]] = {}
    concept_tallies: dict[str, dict[str, int]] = {}
    for row in rows:
        _add_tally(source_tallies, row["source_type"], row["feedback_type"])
        text = " ".join(part for part in (row["title"], row["summary"]) if part)
        for concept_id in detect_concepts_in_text(text):
            _add_tally(concept_tallies, concept_id, row["feedback_type"])
    _persist_feature_tallies(
        connection,
        user_id=user_id,
        feature_kind=FEATURE_KIND_SOURCE_TYPE,
        tallies=source_tallies,
    )
    _persist_feature_tallies(
        connection,
        user_id=user_id,
        feature_kind=FEATURE_KIND_CONCEPT,
        tallies=concept_tallies,
    )


def _empty_tally() -> dict[str, int]:
    return {name: 0 for name in RANKING_FEATURE_TYPES}


def _add_tally(tallies: dict[str, dict[str, int]], feature_value: str, feedback_type: str) -> None:
    bucket = tallies.setdefault(feature_value, _empty_tally())
    if feedback_type in bucket:
        bucket[feedback_type] += 1


def _persist_feature_tallies(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feature_kind: str,
    tallies: dict[str, dict[str, int]],
) -> None:
    for feature_value, counts in tallies.items():
        connection.execute(
            """
            INSERT INTO user_ranking_features (
                user_id, feature_kind, feature_value,
                important_count, not_relevant_count,
                follow_count, already_knew_count, learned_now_count, less_like_this_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                feature_kind,
                feature_value,
                counts["important"],
                counts["not_relevant"],
                counts["follow"],
                counts["already_knew"],
                counts["learned_now"],
                counts["less_like_this"],
            ),
        )


def adjustment_for_counts(important_count: int, not_relevant_count: int) -> Adjustment | None:
    if important_count >= MIN_SAMPLE_SIZE and important_count > not_relevant_count:
        return "boost_importance"
    if not_relevant_count >= MIN_SAMPLE_SIZE and not_relevant_count > important_count:
        return "demote_relation"
    return None


def _reset_at(connection: sqlite3.Connection, user_id: str) -> int:
    row = connection.execute(
        "SELECT reset_at FROM user_ranking_resets WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["reset_at"]) if row is not None else -1


def _shift(level: str, order: tuple[str, ...], delta: int) -> str:
    try:
        index = order.index(level)
    except ValueError:
        return level
    return order[max(0, min(len(order) - 1, index + delta))]


def _features(
    connection: sqlite3.Connection,
    user_id: str,
    feature_kind: str = FEATURE_KIND_SOURCE_TYPE,
) -> dict[str, tuple[int, int]]:
    return {
        row["feature_value"]: (int(row["important_count"]), int(row["not_relevant_count"]))
        for row in connection.execute(
            """
            SELECT feature_value, important_count, not_relevant_count
            FROM user_ranking_features
            WHERE user_id = ? AND feature_kind = ?
            """,
            (user_id, feature_kind),
        )
    }


def _explain(kind: Adjustment, count: int, feature_value: str) -> str:
    if kind == "boost_importance":
        action = f"{count} important marks"
    else:
        action = f"{count} not_relevant marks"
    return (
        f"Personalized from {action} on {feature_value} items "
        f"[{PERSONALIZATION_VERSION}]."
    )


def _apply_adjustments(
    connection: sqlite3.Connection,
    *, user_id: str,
    preference: UserPreferenceState,
) -> int:
    features = _features(connection, user_id)
    concept_features = _features(connection, user_id, FEATURE_KIND_CONCEPT)
    items = connection.execute(
        """
        SELECT f.id, f.event_id, d.type AS delta_type, e.title, e.summary,
               COALESCE(le.source_type, 'unknown') AS source_type,
               COALESCE(le.source_key, '') AS source_key
        FROM feed_items f
        JOIN deltas d ON d.id = f.delta_id
        JOIN events e ON e.id = f.event_id
        LEFT JOIN ledger_events le ON le.id = f.event_id
        WHERE f.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    updated = 0
    for item in items:
        source_type = item["source_type"]
        importance = evaluate_importance(
            source_type=source_type,
            delta_type=item["delta_type"],
        )
        relation = evaluate_relation(
            connection,
            user_id=user_id,
            source_type=source_type,
            source_key=item["source_key"],
            event_title=item["title"],
            event_summary=item["summary"],
        )
        importance_level = importance.level
        importance_reason = importance.reason
        relation_level = relation.level
        relation_reason = relation.reason
        personalization_rank = relation.personalization_rank
        counts = features.get(source_type, (0, 0))
        kind = adjustment_for_counts(*counts)
        feature_value = source_type
        if kind is None:
            text = " ".join(part for part in (item["title"], item["summary"]) if part)
            for concept_id in detect_concepts_in_text(text):
                concept_counts = concept_features.get(concept_id, (0, 0))
                concept_kind = adjustment_for_counts(*concept_counts)
                if concept_kind is not None:
                    kind = concept_kind
                    counts = concept_counts
                    feature_value = concept_id
                    break
        if kind == "boost_importance":
            importance_level = _shift(importance_level, _IMPORTANCE_ORDER, 1)
            importance_reason = f"{importance.reason} {_explain(kind, counts[0], feature_value)}"
            personalization_rank = relation.personalization_rank + RANK_BONUS
        elif kind == "demote_relation":
            relation_level = _shift(relation_level, _RELATION_ORDER, -1)
            suffix = _explain(kind, counts[1], feature_value)
            relation_reason = f"{relation.reason} {suffix}".strip()
            personalization_rank = max(0, relation.personalization_rank - RANK_BONUS)
        has_explicit = relation.level == "direct" or bool(relation.matched_topics) or bool(
            relation.matched_repositories
        )
        overlay = preference_overlay(
            preference,
            source_type=source_type,
            text=" ".join(part for part in (item["title"], item["summary"]) if part),
            has_explicit_authority=has_explicit,
        )
        if overlay.applied:
            # Rank-only. Preference never rewrites importance/relation levels;
            # explicit topic/repo matches use a smaller cap than implicit items.
            personalization_rank = max(0, personalization_rank + overlay.rank_delta)
            if overlay.debug:
                importance_reason = f"{importance_reason} {overlay.debug}".strip()
        connection.execute(
            """
            UPDATE feed_items
            SET importance_level = ?, importance_reason = ?, importance_confidence = ?,
                relation_level = ?, relation_reason = ?, relation_score = ?,
                relation_feature_version = ?, matched_topics_json = ?,
                matched_repos_json = ?, personalization_rank = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                importance_level,
                importance_reason,
                importance.confidence,
                relation_level,
                relation_reason,
                relation.score,
                relation.feature_version,
                json.dumps(relation.matched_topics),
                json.dumps(relation.matched_repositories),
                personalization_rank,
                item["id"],
                user_id,
            ),
        )
        updated += 1
    return updated
