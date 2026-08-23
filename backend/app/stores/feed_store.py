from __future__ import annotations

import base64
import binascii
import json
import secrets
import sqlite3
from datetime import UTC, datetime

from app.database import Database
from app.errors import not_found, unprocessable
from app.schemas.common import Delta, Importance, MatchedRepository, Relation, SourceEvidence
from app.schemas.feed import PublicFeedItem

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
                WHERE f.user_id = ? AND f.dismissed = 0
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
            params: list[object] = [user_id, int(datetime.now(UTC).timestamp())]
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
        return {"feed_item_id": feed_item_id, "status": "read"}

    def save_feedback(self, user_id: str, feed_item_id: str, feedback_type: str) -> dict:
        if feedback_type not in {"important", "not_relevant"}:
            raise unprocessable("feedback type is invalid")
        now = int(datetime.now().timestamp())
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, status FROM feed_items WHERE id = ? AND user_id = ?",
                (feed_item_id, user_id),
            ).fetchone()
            if row is None:
                raise not_found("Feed item was not found")
            connection.execute(
                "INSERT INTO feedback (id, feed_item_id, user_id, type, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    f"fb_{secrets.token_urlsafe(8)}",
                    feed_item_id,
                    user_id,
                    feedback_type,
                    now,
                ),
            )
            if feedback_type == "not_relevant":
                connection.execute(
                    "UPDATE feed_items SET dismissed = 1, status = 'read' WHERE id = ? AND user_id = ?",
                    (feed_item_id, user_id),
                )
            else:
                connection.execute(
                    "UPDATE feed_items SET marked_important = 1 WHERE id = ? AND user_id = ?",
                    (feed_item_id, user_id),
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
                    SELECT d.id, f.delta_id, m.claim_id
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
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO user_claim_exposures (
                            user_id, claim_id, delivery_id, delivered_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (user_id, delivery["claim_id"], delivery_id, item["displayed_at"]),
                    )
                accepted += inserted
        return accepted
