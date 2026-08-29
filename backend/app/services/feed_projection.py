from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from app.database import Database
from app.db.knownness import WATERMARK_STATES
from app.db.projection_schema import ensure_projection_schema
from app.observability import record
from app.services.ranking import evaluate_importance
from app.services.ranking_feedback import apply_feedback_ranking
from app.services.relation import _normalize, evaluate_relation

if len(WATERMARK_STATES) != 2:
    raise RuntimeError("novel-delta SQL binds exactly two watermark states")


def project_event_for_audience(
    database: Database,
    *,
    event_id: str,
    user_ids: Sequence[str],
) -> dict[str, list[str]]:
    """Project one already-ingested Event onto an explicit user audience.

    Callers resolve who is subscribed. This helper does not discover
    subscribers and does not write user_claim_exposures.
    """
    projector = FeedProjector(database)
    created: dict[str, list[str]] = {}
    for user_id in dict.fromkeys(user_ids):
        created[user_id] = projector.project_event_for_user(user_id=user_id, event_id=event_id)
    return created


class FeedProjector:
    def __init__(self, database: Database) -> None:
        self._database = database
        ensure_projection_schema(database)

    def project_event_for_user(self, *, user_id: str, event_id: str) -> list[str]:
        created: list[str] = []
        with self._database.connect() as connection:
            event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if event is None:
                raise ValueError(f"public event {event_id} not found")
            source_type, source_key = self._source_identity(connection, event_id)
            relation = evaluate_relation(
                connection,
                user_id=user_id,
                source_type=source_type,
                source_key=source_key,
                event_title=event["title"],
                event_summary=event["summary"],
            )

            # (?, ?) matches WATERMARK_STATES. Bindings fail if that tuple changes.
            deltas = connection.execute(
                """
                SELECT d.*
                FROM deltas d
                JOIN delta_claim_map m ON m.delta_id = d.id
                JOIN state_claims candidate ON candidate.id = m.claim_id
                LEFT JOIN user_claim_exposures k
                    ON k.claim_id = m.claim_id AND k.user_id = ?
                   AND k.state IN (?, ?)
                WHERE d.event_id = ?
                  AND d.active = 1
                  AND k.claim_id IS NULL
                  AND (
                      d.type = 'correction'
                      OR candidate.valid_at >= COALESCE((
                          SELECT MAX(known_claim.valid_at)
                          FROM user_claim_exposures known
                          JOIN state_claims known_claim ON known_claim.id = known.claim_id
                          WHERE known.user_id = ? AND known_claim.event_id = d.event_id
                            AND known.state IN (?, ?)
                      ), '')
                  )
                ORDER BY d.occurred_at, d.id
                """,
                (user_id, *WATERMARK_STATES, event_id, user_id, *WATERMARK_STATES),
            ).fetchall()
            for delta in deltas:
                feed_item_id = self._stable_id("fi", f"{user_id}|{delta['id']}")
                importance = evaluate_importance(
                    source_type=source_type,
                    delta_type=delta["type"],
                )
                connection.execute(
                    """
                    INSERT INTO feed_items (
                        id, user_id, event_id, delta_id, title,
                        importance_level, importance_reason, importance_confidence,
                        relation_level, relation_reason, matched_topics_json,
                        matched_repos_json, personalization_rank,
                        status, dismissed, marked_important, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unread', 0, 0, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        importance_level = excluded.importance_level,
                        importance_reason = excluded.importance_reason,
                        importance_confidence = excluded.importance_confidence,
                        relation_level = excluded.relation_level,
                        relation_reason = excluded.relation_reason,
                        matched_topics_json = excluded.matched_topics_json,
                        matched_repos_json = excluded.matched_repos_json,
                        personalization_rank = excluded.personalization_rank,
                        dismissed = CASE
                            WHEN excluded.relation_level = 'reference' THEN feed_items.dismissed
                            ELSE 0
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        feed_item_id,
                        user_id,
                        event_id,
                        delta["id"],
                        event["title"],
                        importance.level,
                        importance.reason,
                        importance.confidence,
                        relation.level,
                        relation.reason,
                        json.dumps(relation.matched_topics),
                        json.dumps(relation.matched_repositories),
                        relation.personalization_rank,
                        delta["occurred_at"],
                    ),
                )
                created.append(feed_item_id)
            apply_feedback_ranking(connection, user_id=user_id)
        record(
            "projection",
            layer="feed",
            event_id=event_id,
            user_id=user_id,
            feed_item_count=len(created),
        )
        return created

    def reproject_user(self, *, user_id: str) -> int:
        """Project candidate events, then recompute the user's relation/rank.

        Candidates are existing feed items plus events that can match the user's
        topics or selected repositories. Unrelated global events are not scanned.
        """
        with self._database.connect() as connection:
            event_ids = self._candidate_event_ids(connection, user_id=user_id)
        for event_id in event_ids:
            self.project_event_for_user(user_id=user_id, event_id=event_id)

        updated = 0
        with self._database.connect() as connection:
            events = connection.execute(
                """
                SELECT DISTINCT e.id, e.title, e.summary
                FROM feed_items f
                JOIN events e ON e.id = f.event_id
                WHERE f.user_id = ?
                """,
                (user_id,),
            ).fetchall()
            for event in events:
                source_type, source_key = self._source_identity(connection, event["id"])
                relation = evaluate_relation(
                    connection,
                    user_id=user_id,
                    source_type=source_type,
                    source_key=source_key,
                    event_title=event["title"],
                    event_summary=event["summary"],
                )
                updated += connection.execute(
                    """
                    UPDATE feed_items
                    SET relation_level = ?, relation_reason = ?,
                        matched_topics_json = ?, matched_repos_json = ?,
                        personalization_rank = ?
                    WHERE user_id = ? AND event_id = ?
                    """,
                    (
                        relation.level,
                        relation.reason,
                        json.dumps(relation.matched_topics),
                        json.dumps(relation.matched_repositories),
                        relation.personalization_rank,
                        user_id,
                        event["id"],
                    ),
                ).rowcount
            apply_feedback_ranking(connection, user_id=user_id)
            topic_count = connection.execute(
                "SELECT COUNT(*) FROM topics WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            repository_count = connection.execute(
                "SELECT COUNT(*) FROM github_repo_watches WHERE user_id = ? AND selected = 1",
                (user_id,),
            ).fetchone()[0]
            # A user with no topics or selected repositories should see an empty
            # feed. Once they follow anything, reference items remain visible in
            # the ALL view even when a particular change has no direct match.
            if topic_count == 0 and repository_count == 0:
                connection.execute(
                    """
                    UPDATE feed_items
                    SET dismissed = 1
                    WHERE user_id = ?
                      AND relation_level = 'reference'
                      AND matched_topics_json = '[]'
                      AND matched_repos_json = '[]'
                    """,
                    (user_id,),
                )
            else:
                connection.execute(
                    """
                    UPDATE feed_items
                    SET dismissed = 0
                    WHERE user_id = ?
                      AND relation_level = 'reference'
                    """,
                    (user_id,),
                )
        return updated

    @staticmethod
    def _candidate_event_ids(connection, *, user_id: str) -> list[str]:
        ids: set[str] = set()
        for row in connection.execute(
            "SELECT DISTINCT event_id FROM feed_items WHERE user_id = ?",
            (user_id,),
        ):
            ids.add(row["event_id"])
        for row in connection.execute(
            """
            SELECT e.id
            FROM events e
            JOIN ledger_events le ON le.id = e.id
            JOIN github_repo_watches w
              ON w.user_id = ?
             AND w.selected = 1
             AND w.full_name = le.source_key
            """,
            (user_id,),
        ):
            ids.add(row["id"])
        topics = [
            token
            for (name,) in connection.execute(
                "SELECT name FROM topics WHERE user_id = ?",
                (user_id,),
            )
            if (token := _normalize(name))
        ]
        if topics:
            events = connection.execute(
                """
                SELECT e.id, e.title, e.summary, COALESCE(le.source_key, '') AS source_key
                FROM events e
                LEFT JOIN ledger_events le ON le.id = e.id
                """
            ).fetchall()
            for event in events:
                padded = f" {_normalize(' '.join((event['source_key'], event['title'], event['summary'])))} "
                if any(f" {token} " in padded for token in topics):
                    ids.add(event["id"])
        return sorted(ids)

    @staticmethod
    def _source_identity(connection, event_id: str) -> tuple[str, str]:
        ledger_event = connection.execute(
            "SELECT source_type, source_key FROM ledger_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if ledger_event is None:
            return "unknown", ""
        return ledger_event["source_type"], ledger_event["source_key"]

    @staticmethod
    def _stable_id(prefix: str, raw: str) -> str:
        return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
