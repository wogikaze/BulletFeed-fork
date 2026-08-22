from __future__ import annotations

import base64
import json
import secrets
import sqlite3
from datetime import UTC, datetime

from app.database import Database
from app.db.seed import seed_user_workspace
from app.errors import not_found, unprocessable
from app.schemas.common import Delta, Importance, MatchedRepository, Relation
from app.schemas.feed import PublicFeedItem

_VALID_RELATIONS = {"direct", "adjacent", "reference"}
_VALID_STATUSES = {"unread", "read"}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _encode_cursor(updated_at: str, item_id: str) -> str:
    raw = f"{updated_at}|{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    padding = "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(cursor + padding).decode()
        updated_at, item_id = decoded.split("|", 1)
    except (ValueError, UnicodeDecodeError) as exc:
        raise unprocessable("cursor is invalid") from exc
    return updated_at, item_id


def _row_to_item(row: sqlite3.Row, delivery_id: str, following: bool) -> PublicFeedItem:
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
    )


class FeedStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def _ensure_workspace(self, connection: sqlite3.Connection, user_id: str) -> None:
        seed_user_workspace(connection, user_id)

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

        cursor_updated_at: str | None = None
        cursor_id: str | None = None
        if cursor:
            cursor_updated_at, cursor_id = _decode_cursor(cursor)

        with self._database.connect() as connection:
            self._ensure_workspace(connection, user_id)
            follows = {
                row["event_id"]: bool(row["following"])
                for row in connection.execute(
                    "SELECT event_id, following FROM event_follows WHERE user_id = ?",
                    (user_id,),
                )
            }
            fetched = connection.execute(
                """
                SELECT f.*, d.type AS delta_type, d.summary AS delta_summary,
                       d.before_text, d.after_text, d.occurred_at
                FROM feed_items f
                JOIN deltas d ON d.id = f.delta_id
                WHERE f.user_id = ? AND f.dismissed = 0
                ORDER BY f.updated_at DESC, f.id DESC
                """,
                (user_id,),
            ).fetchall()
            rows = []
            for row in fetched:
                if relation and row["relation_level"] != relation:
                    continue
                if item_status and row["status"] != item_status:
                    continue
                if cursor_updated_at and cursor_id:
                    older = row["updated_at"] < cursor_updated_at
                    same_page = row["updated_at"] == cursor_updated_at and row["id"] < cursor_id
                    if not (older or same_page):
                        continue
                rows.append(row)
            page_rows = rows[:limit]
            items: list[PublicFeedItem] = []
            created_at = _now_iso()
            for row in page_rows:
                delivery_id = f"dlv_{secrets.token_urlsafe(10)}"
                connection.execute(
                    "INSERT INTO deliveries (id, feed_item_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                    (delivery_id, row["id"], user_id, created_at),
                )
                items.append(_row_to_item(row, delivery_id, follows.get(row["event_id"], False)))
            next_cursor = None
            if len(rows) > limit:
                last = page_rows[-1]
                next_cursor = _encode_cursor(last["updated_at"], last["id"])
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
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM feed_items WHERE id = ? AND user_id = ?",
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
                    int(datetime.now().timestamp()),
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
        item_status = "read" if feedback_type == "not_relevant" else "unread"
        with self._database.connect() as connection:
            current = connection.execute(
                "SELECT status FROM feed_items WHERE id = ?",
                (feed_item_id,),
            ).fetchone()
            if current is not None:
                item_status = current["status"]
        return {"feed_item_id": feed_item_id, "type": feedback_type, "status": item_status}

    def record_exposures(self, user_id: str, items: list[dict[str, str]]) -> int:
        accepted = 0
        now = int(datetime.now().timestamp())
        with self._database.connect() as connection:
            for item in items:
                delivery_id = item["delivery_id"]
                owned = connection.execute(
                    "SELECT id FROM deliveries WHERE id = ? AND user_id = ?",
                    (delivery_id, user_id),
                ).fetchone()
                if owned is None:
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO exposures (delivery_id, user_id, displayed_at, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (delivery_id, user_id, item["displayed_at"], now),
                )
                accepted += 1
        return accepted
