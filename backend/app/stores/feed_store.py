from __future__ import annotations

import base64
import binascii
import json
import secrets
import sqlite3
from datetime import UTC, datetime

from app.database import Database
from app.db.knownness import (
    KNOWNNESS_DELIVERED,
    KNOWNNESS_DISPLAYED,
    KNOWNNESS_READ,
    UNDISPLAYED_DELIVERY_RETRY_LIMIT,
)
from app.errors import not_found, unprocessable
from app.schemas.common import Delta, Importance, MatchedRepository, Relation, SourceEvidence
from app.schemas.feed import PublicFeedItem
from app.services.feedback_signals import (
    FAMILY_FOLLOW,
    FAMILY_KNOWLEDGE,
    FAMILY_PREFERENCE,
    FAMILY_RANKING,
    is_allowed_feedback_type,
    latest_family_for_item,
    resolve_write_family,
    types_for_family,
)
from app.services.knowledge_evidence import (
    KIND_ALREADY_KNEW,
    KIND_DELIVERED,
    KIND_DISPLAYED,
    KIND_LEARNED_NOW,
    KIND_READ,
    append_knowledge_evidence,
)

_VALID_RELATIONS = {"direct", "adjacent", "reference"}
_VALID_STATUSES = {"unread", "read"}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _encode_cursor(
    importance_rank: int,
    relation_rank: int,
    personalization_rank: int,
    updated_at: str,
    item_id: str,
) -> str:
    raw = (
        f"v3|{importance_rank}|{relation_rank}|{personalization_rank}|{updated_at}|{item_id}"
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, int, int, str, str]:
    padding = "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(cursor + padding).decode()
        version, importance_rank, relation_rank, personalization_rank, updated_at, item_id = decoded.split(
            "|", 5
        )
        if version != "v3" or not updated_at or not item_id:
            raise ValueError
        return (
            int(importance_rank),
            int(relation_rank),
            int(personalization_rank),
            updated_at,
            item_id,
        )
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise unprocessable("cursor is invalid or from an obsolete ranking version") from exc


def _row_to_item(
    row: sqlite3.Row,
    delivery_id: str,
    following: bool,
    sources: list[SourceEvidence],
) -> PublicFeedItem:
    return PublicFeedItem(
        id=row["id"],
        event_id=row["event_id"],
        delta=Delta(
            id=row["delta_id"],
            type=row["delta_type"],
            summary=row["delta_summary"],
            before=row["before_text"],
            after=row["after_text"],
            occurred_at=row["occurred_at"],
        ),
        title=row["title"],
        importance=Importance(
            level=row["importance_level"],
            reason=row["importance_reason"],
            confidence=row["importance_confidence"],
        ),
        relation=Relation(
            level=row["relation_level"],
            reason=row["relation_reason"],
            matched_topics=json.loads(row["matched_topics_json"]),
            matched_repositories=[
                MatchedRepository.model_validate(item) for item in json.loads(row["matched_repos_json"])
            ],
        ),
        status=row["status"],
        following=following,
        updated_at=row["updated_at"],
        delivery_id=delivery_id,
        sources=sources,
    )


def _upsert_delivered(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str,
    delivery_id: str,
    delivered_at: str,
    event_id: str | None = None,
    delta_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO user_claim_exposures (
            user_id, claim_id, delivery_id, delivered_at, state,
            displayed_at, read_at, delivery_count
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 1)
        ON CONFLICT(user_id, claim_id) DO UPDATE SET
            delivery_id = CASE
                WHEN user_claim_exposures.state = 'delivered'
                THEN excluded.delivery_id
                ELSE user_claim_exposures.delivery_id
            END,
            delivered_at = CASE
                WHEN user_claim_exposures.state = 'delivered'
                THEN excluded.delivered_at
                ELSE user_claim_exposures.delivered_at
            END,
            delivery_count = CASE
                WHEN user_claim_exposures.state = 'delivered'
                THEN user_claim_exposures.delivery_count + 1
                ELSE user_claim_exposures.delivery_count
            END
        """,
        (user_id, claim_id, delivery_id, delivered_at, KNOWNNESS_DELIVERED),
    )
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_DELIVERED,
        source_id=delivery_id,
        claim_id=claim_id,
        event_id=event_id,
        delta_id=delta_id,
    )


def _upsert_displayed(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str,
    delivery_id: str,
    displayed_at: str,
    event_id: str | None = None,
    delta_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO user_claim_exposures (
            user_id, claim_id, delivery_id, delivered_at, state,
            displayed_at, read_at, delivery_count
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, 1)
        ON CONFLICT(user_id, claim_id) DO UPDATE SET
            state = CASE
                WHEN user_claim_exposures.state = 'read' THEN 'read'
                ELSE 'displayed'
            END,
            displayed_at = COALESCE(user_claim_exposures.displayed_at, excluded.displayed_at),
            delivery_id = CASE
                WHEN user_claim_exposures.state = 'delivered' THEN excluded.delivery_id
                ELSE user_claim_exposures.delivery_id
            END
        """,
        (
            user_id,
            claim_id,
            delivery_id,
            displayed_at,
            KNOWNNESS_DISPLAYED,
            displayed_at,
        ),
    )
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_DISPLAYED,
        source_id=delivery_id,
        claim_id=claim_id,
        event_id=event_id,
        delta_id=delta_id,
    )


def _record_read(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
) -> None:
    mapped = connection.execute(
        """
        SELECT m.claim_id, f.event_id, f.delta_id
        FROM feed_items f
        JOIN delta_claim_map m ON m.delta_id = f.delta_id
        WHERE f.id = ? AND f.user_id = ?
        """,
        (feed_item_id, user_id),
    ).fetchone()
    if mapped is None:
        return
    delivery = connection.execute(
        """
        SELECT id, created_at
        FROM deliveries
        WHERE feed_item_id = ? AND user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (feed_item_id, user_id),
    ).fetchone()
    now = _now_iso()
    if delivery is None:
        delivery_id = f"dlv_{secrets.token_urlsafe(10)}"
        connection.execute(
            "INSERT INTO deliveries (id, feed_item_id, user_id, created_at) VALUES (?, ?, ?, ?)",
            (delivery_id, feed_item_id, user_id, now),
        )
        delivered_at = now
    else:
        delivery_id = delivery["id"]
        delivered_at = delivery["created_at"]
    connection.execute(
        """
        INSERT INTO user_claim_exposures (
            user_id, claim_id, delivery_id, delivered_at, state,
            displayed_at, read_at, delivery_count
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, 1)
        ON CONFLICT(user_id, claim_id) DO UPDATE SET
            state = 'read',
            read_at = COALESCE(user_claim_exposures.read_at, excluded.read_at)
        """,
        (
            user_id,
            mapped["claim_id"],
            delivery_id,
            delivered_at,
            KNOWNNESS_READ,
            now,
        ),
    )
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_READ,
        source_id=delivery_id,
        claim_id=mapped["claim_id"],
        event_id=mapped["event_id"],
        delta_id=mapped["delta_id"],
    )


def _next_created_at(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
) -> int:
    """Second-resolution clock, incremented when the same item is written again.

    Ranking reset compares `feedback.created_at > reset_at` in seconds. Latest-state
    still needs a total order, so a same-second write on the same item steps +1.
    """
    now = int(datetime.now().timestamp())
    latest = connection.execute(
        """
        SELECT MAX(created_at) AS created_at
        FROM feedback
        WHERE user_id = ? AND feed_item_id = ?
        """,
        (user_id, feed_item_id),
    ).fetchone()
    latest_at = latest["created_at"] if latest is not None else None
    if latest_at is not None and now <= int(latest_at):
        return int(latest_at) + 1
    return now


def _supersede_family(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
    family: str | None,
) -> None:
    if family is None:
        return
    family_types = types_for_family(family)
    placeholders = ", ".join("?" for _ in family_types) if family_types else "?"
    type_params: tuple[str, ...] = tuple(sorted(family_types)) if family_types else ("",)
    connection.execute(
        f"""
        UPDATE feedback
        SET superseded = 1
        WHERE user_id = ? AND feed_item_id = ? AND superseded = 0
          AND (
              family = ?
              OR (family IS NULL AND type IN ({placeholders}))
          )
        """,
        (user_id, feed_item_id, family, *type_params),
    )


def _apply_feedback_derived_state(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    feed_item_id: str,
    event_id: str,
    delta_id: str,
    claim_id: str | None,
    feedback_type: str,
    family: str | None,
    created_at: int,
) -> None:
    if family == FAMILY_RANKING:
        if feedback_type == "not_relevant":
            connection.execute(
                """
                UPDATE feed_items
                SET dismissed = 1, status = 'read'
                WHERE id = ? AND user_id = ?
                """,
                (feed_item_id, user_id),
            )
        elif feedback_type == "important":
            connection.execute(
                """
                UPDATE feed_items
                SET marked_important = 1, dismissed = 0
                WHERE id = ? AND user_id = ?
                """,
                (feed_item_id, user_id),
            )
        elif feedback_type == "undo":
            connection.execute(
                """
                UPDATE feed_items
                SET marked_important = 0, dismissed = 0
                WHERE id = ? AND user_id = ?
                """,
                (feed_item_id, user_id),
            )
        return

    if family == FAMILY_FOLLOW:
        following = 0 if feedback_type == "undo" else 1
        connection.execute(
            """
            INSERT INTO event_follows (user_id, event_id, following)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, event_id) DO UPDATE SET following = excluded.following
            """,
            (user_id, event_id, following),
        )
        return

    if family == FAMILY_KNOWLEDGE:
        connection.execute(
            """
            UPDATE user_knowledge_signals
            SET superseded = 1
            WHERE user_id = ? AND feed_item_id = ? AND superseded = 0
            """,
            (user_id, feed_item_id),
        )
        if feedback_type != "undo":
            connection.execute(
                """
                INSERT INTO user_knowledge_signals (
                    id, user_id, feed_item_id, event_id, delta_id, claim_id,
                    signal, created_at, superseded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    f"uks_{secrets.token_urlsafe(8)}",
                    user_id,
                    feed_item_id,
                    event_id,
                    delta_id,
                    claim_id,
                    feedback_type,
                    created_at,
                ),
            )
        return

    if family == FAMILY_PREFERENCE:
        return


class FeedStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_feed(
        self,
        user_id: str,
        *,
        relation: str | None,
        item_status: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[PublicFeedItem], str | None]:
        if relation is not None and relation not in _VALID_RELATIONS:
            raise unprocessable("relation is invalid")
        if item_status is not None and item_status not in _VALID_STATUSES:
            raise unprocessable("status is invalid")
        if limit < 1 or limit > 50:
            raise unprocessable("limit must be 1-50")

        cursor_values: tuple[int, int, int, str, str] | None = None
        if cursor:
            cursor_values = _decode_cursor(cursor)

        with self._database.connect() as connection:
            follows = {
                row["event_id"]: bool(row["following"])
                for row in connection.execute(
                    "SELECT event_id, following FROM event_follows WHERE user_id = ?",
                    (user_id,),
                )
            }

            inner_sql = """
                SELECT f.*, d.type AS delta_type, d.summary AS delta_summary,
                       d.before_text, d.after_text, d.occurred_at,
                       claim_map.claim_id AS claim_id,
                       CASE f.importance_level
                           WHEN 'critical' THEN 4
                           WHEN 'high' THEN 3
                           WHEN 'medium' THEN 2
                           ELSE 1
                       END AS importance_rank,
                       CASE f.relation_level
                           WHEN 'direct' THEN 3
                           WHEN 'adjacent' THEN 2
                           ELSE 1
                       END AS relation_rank
                FROM feed_items f
                JOIN deltas d ON d.id = f.delta_id
                LEFT JOIN delta_claim_map claim_map ON claim_map.delta_id = f.delta_id
                LEFT JOIN user_claim_exposures knownness
                    ON knownness.user_id = f.user_id
                   AND knownness.claim_id = claim_map.claim_id
                WHERE f.user_id = ? AND f.dismissed = 0
                  AND (
                      knownness.claim_id IS NULL
                      OR knownness.state != ?
                      OR knownness.delivery_count < ?
                  )
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM event_visibility v
                          WHERE v.event_id = f.event_id AND v.restricted = 1
                      )
                      OR EXISTS (
                          SELECT 1 FROM event_user_access a
                          WHERE a.event_id = f.event_id
                            AND a.user_id = f.user_id
                            AND a.expires_at > ?
                      )
                  )
            """
            params: list[object] = [
                user_id,
                KNOWNNESS_DELIVERED,
                UNDISPLAYED_DELIVERY_RETRY_LIMIT,
                int(datetime.now(UTC).timestamp()),
            ]
            if relation is not None:
                inner_sql += " AND f.relation_level = ?"
                params.append(relation)
            if item_status is not None:
                inner_sql += " AND f.status = ?"
                params.append(item_status)

            sql = f"SELECT * FROM ({inner_sql}) ranked"  # nosec B608
            if cursor_values is not None:
                importance_rank, relation_rank, personalization_rank, updated_at, item_id = cursor_values
                sql += """
                    WHERE importance_rank < ?
                       OR (importance_rank = ? AND relation_rank < ?)
                       OR (
                           importance_rank = ? AND relation_rank = ?
                           AND personalization_rank < ?
                       )
                       OR (
                           importance_rank = ? AND relation_rank = ?
                           AND personalization_rank = ? AND updated_at < ?
                       )
                       OR (
                           importance_rank = ? AND relation_rank = ?
                           AND personalization_rank = ? AND updated_at = ? AND id < ?
                       )
                """
                params.extend(
                    [
                        importance_rank,
                        importance_rank,
                        relation_rank,
                        importance_rank,
                        relation_rank,
                        personalization_rank,
                        importance_rank,
                        relation_rank,
                        personalization_rank,
                        updated_at,
                        importance_rank,
                        relation_rank,
                        personalization_rank,
                        updated_at,
                        item_id,
                    ]
                )
            sql += """
                ORDER BY importance_rank DESC, relation_rank DESC,
                         personalization_rank DESC, updated_at DESC, id DESC
                LIMIT ?
            """
            params.append(limit + 1)

            rows = list(connection.execute(sql, params).fetchall())
            page_rows = rows[:limit]
            sources_by_event: dict[str, list[SourceEvidence]] = {}
            event_ids = list(dict.fromkeys(row["event_id"] for row in page_rows))
            if event_ids:
                placeholders = ",".join("?" for _ in event_ids)
                source_rows = connection.execute(
                    f"""
                    SELECT event_id, publisher, kind, title, url, published_at, retrieved_at, evidence
                    FROM event_sources
                    WHERE event_id IN ({placeholders})
                    ORDER BY published_at, id
                    """,  # nosec B608
                    event_ids,
                ).fetchall()
                for source in source_rows:
                    sources_by_event.setdefault(source["event_id"], []).append(
                        SourceEvidence(
                            publisher=source["publisher"],
                            kind=source["kind"],
                            title=source["title"],
                            url=source["url"],
                            published_at=source["published_at"],
                            retrieved_at=source["retrieved_at"],
                            evidence=source["evidence"],
                        )
                    )

            items: list[PublicFeedItem] = []
            created_at = _now_iso()
            for row in page_rows:
                delivery_id = f"dlv_{secrets.token_urlsafe(10)}"
                connection.execute(
                    "INSERT INTO deliveries (id, feed_item_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                    (delivery_id, row["id"], user_id, created_at),
                )
                if row["claim_id"] is not None:
                    _upsert_delivered(
                        connection,
                        user_id=user_id,
                        claim_id=row["claim_id"],
                        delivery_id=delivery_id,
                        delivered_at=created_at,
                        event_id=row["event_id"],
                        delta_id=row["delta_id"],
                    )
                items.append(
                    _row_to_item(
                        row,
                        delivery_id,
                        follows.get(row["event_id"], False),
                        sources_by_event.get(row["event_id"], []),
                    )
                )

            next_cursor = None
            if len(rows) > limit and page_rows:
                last = page_rows[-1]
                next_cursor = _encode_cursor(
                    last["importance_rank"],
                    last["relation_rank"],
                    last["personalization_rank"],
                    last["updated_at"],
                    last["id"],
                )
            return items, next_cursor

    def mark_read(self, user_id: str, feed_item_id: str) -> dict:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, status FROM feed_items WHERE id = ? AND user_id = ?",
                (feed_item_id, user_id),
            ).fetchone()
            if row is None:
                raise not_found("Feed item was not found")
            connection.execute(
                "UPDATE feed_items SET status = 'read' WHERE id = ? AND user_id = ?",
                (feed_item_id, user_id),
            )
            _record_read(connection, user_id=user_id, feed_item_id=feed_item_id)
        return {"feed_item_id": feed_item_id, "status": "read"}

    def save_feedback(self, user_id: str, feed_item_id: str, feedback_type: str) -> dict:
        if not is_allowed_feedback_type(feedback_type):
            raise unprocessable("feedback type is invalid")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT f.id, f.status, f.event_id, f.delta_id, m.claim_id
                FROM feed_items f
                LEFT JOIN delta_claim_map m ON m.delta_id = f.delta_id
                WHERE f.id = ? AND f.user_id = ?
                """,
                (feed_item_id, user_id),
            ).fetchone()
            if row is None:
                raise not_found("Feed item was not found")
            event_id = row["event_id"]
            delta_id = row["delta_id"]
            claim_id = row["claim_id"]
            family = resolve_write_family(
                feedback_type=feedback_type,
                latest_family=latest_family_for_item(
                    connection,
                    user_id=user_id,
                    feed_item_id=feed_item_id,
                ),
            )
            now = _next_created_at(
                connection,
                user_id=user_id,
                feed_item_id=feed_item_id,
            )
            _supersede_family(
                connection,
                user_id=user_id,
                feed_item_id=feed_item_id,
                family=family,
            )
            feedback_id = f"fb_{secrets.token_urlsafe(8)}"
            connection.execute(
                """
                INSERT INTO feedback (
                    id, feed_item_id, user_id, type, created_at,
                    event_id, delta_id, claim_id, family, superseded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    feedback_id,
                    feed_item_id,
                    user_id,
                    feedback_type,
                    now,
                    event_id,
                    delta_id,
                    claim_id,
                    family,
                ),
            )
            if family == FAMILY_KNOWLEDGE and feedback_type in {
                KIND_ALREADY_KNEW,
                KIND_LEARNED_NOW,
            }:
                append_knowledge_evidence(
                    connection,
                    user_id=user_id,
                    kind=feedback_type,
                    source_id=feedback_id,
                    claim_id=claim_id,
                    event_id=event_id,
                    delta_id=delta_id,
                    created_at=now,
                )
            _apply_feedback_derived_state(
                connection,
                user_id=user_id,
                feed_item_id=feed_item_id,
                event_id=event_id,
                delta_id=delta_id,
                claim_id=claim_id,
                feedback_type=feedback_type,
                family=family,
                created_at=now,
            )
            current = connection.execute(
                "SELECT status FROM feed_items WHERE id = ?",
                (feed_item_id,),
            ).fetchone()
            item_status = current["status"] if current is not None else row["status"]
        return {"feed_item_id": feed_item_id, "type": feedback_type, "status": item_status}

    def record_exposures(self, user_id: str, items: list[dict[str, str]]) -> int:
        accepted = 0
        now = int(datetime.now().timestamp())
        with self._database.connect() as connection:
            for item in items:
                delivery_id = item["delivery_id"]
                delivery = connection.execute(
                    """
                    SELECT d.id, f.delta_id, f.event_id, m.claim_id
                    FROM deliveries d
                    JOIN feed_items f ON f.id = d.feed_item_id
                    LEFT JOIN delta_claim_map m ON m.delta_id = f.delta_id
                    WHERE d.id = ? AND d.user_id = ? AND f.user_id = ?
                    """,
                    (delivery_id, user_id, user_id),
                ).fetchone()
                if delivery is None:
                    continue
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO exposures (delivery_id, user_id, displayed_at, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (delivery_id, user_id, item["displayed_at"], now),
                ).rowcount
                if delivery["claim_id"] is not None:
                    _upsert_displayed(
                        connection,
                        user_id=user_id,
                        claim_id=delivery["claim_id"],
                        delivery_id=delivery_id,
                        displayed_at=item["displayed_at"],
                        event_id=delivery["event_id"],
                        delta_id=delivery["delta_id"],
                    )
                accepted += inserted
        return accepted
