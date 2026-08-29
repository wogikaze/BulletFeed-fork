from __future__ import annotations

import json
import sqlite3
import time
from typing import Literal

from app.services.feedback_signals import RANKING_FEATURE_TYPES
from app.services.ranking import evaluate_importance
from app.services.relation import evaluate_relation

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
    """
    rebuild_user_ranking_features(connection, user_id=user_id)
    return _apply_adjustments(connection, user_id=user_id)


def reset_feedback_ranking(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    reset_at: int | None = None,
) -> int:
    """Forget learned ranking features for one user and restore baseline ranks."""
    at = int(time.time()) if reset_at is None else reset_at
    connection.execute(
        """
        INSERT INTO user_ranking_resets (user_id, reset_at) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET reset_at = excluded.reset_at
        """,
        (user_id, at),
    )
    return apply_feedback_ranking(connection, user_id=user_id)


def rebuild_user_ranking_features(connection: sqlite3.Connection, *, user_id: str) -> None:
    reset_at = _reset_at(connection, user_id)
    connection.execute("DELETE FROM user_ranking_features WHERE user_id = ?", (user_id,))
    rows = connection.execute(
        """
        WITH latest AS (
            SELECT
                fb.type AS feedback_type,
                COALESCE(le.source_type, 'unknown') AS feature_value
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
            WHERE fb.rn = 1 AND fb.type != 'undo'
        )
        SELECT feature_value, feedback_type, COUNT(*) AS n
        FROM latest
        GROUP BY feature_value, feedback_type
        """,
        (user_id, reset_at),
    ).fetchall()
    empty = {name: 0 for name in RANKING_FEATURE_TYPES}
    tallies: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = tallies.setdefault(row["feature_value"], dict(empty))
        feedback_type = row["feedback_type"]
        if feedback_type in bucket:
            bucket[feedback_type] = int(row["n"])
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
                FEATURE_KIND_SOURCE_TYPE,
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


def _features(connection: sqlite3.Connection, user_id: str) -> dict[str, tuple[int, int]]:
    return {
        row["feature_value"]: (int(row["important_count"]), int(row["not_relevant_count"]))
        for row in connection.execute(
            """
            SELECT feature_value, important_count, not_relevant_count
            FROM user_ranking_features
            WHERE user_id = ? AND feature_kind = ?
            """,
            (user_id, FEATURE_KIND_SOURCE_TYPE),
        )
    }


def _explain(kind: Adjustment, count: int, source_type: str) -> str:
    if kind == "boost_importance":
        action = f"{count} important marks"
    else:
        action = f"{count} not_relevant marks"
    return (
        f"Personalized from {action} on {source_type} items "
        f"[{PERSONALIZATION_VERSION}]."
    )


def _apply_adjustments(connection: sqlite3.Connection, *, user_id: str) -> int:
    features = _features(connection, user_id)
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
        if kind == "boost_importance":
            importance_level = _shift(importance_level, _IMPORTANCE_ORDER, 1)
            importance_reason = f"{importance.reason} {_explain(kind, counts[0], source_type)}"
            personalization_rank = relation.personalization_rank + RANK_BONUS
        elif kind == "demote_relation":
            relation_level = _shift(relation_level, _RELATION_ORDER, -1)
            suffix = _explain(kind, counts[1], source_type)
            relation_reason = f"{relation.reason} {suffix}".strip()
            personalization_rank = max(0, relation.personalization_rank - RANK_BONUS)
        connection.execute(
            """
            UPDATE feed_items
            SET importance_level = ?, importance_reason = ?, importance_confidence = ?,
                relation_level = ?, relation_reason = ?, matched_topics_json = ?,
                matched_repos_json = ?, personalization_rank = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                importance_level,
                importance_reason,
                importance.confidence,
                relation_level,
                relation_reason,
                json.dumps(relation.matched_topics),
                json.dumps(relation.matched_repositories),
                personalization_rank,
                item["id"],
                user_id,
            ),
        )
        updated += 1
    return updated
