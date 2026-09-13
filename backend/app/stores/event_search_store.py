from __future__ import annotations

import base64
import binascii
import json
import time

from app.database import Database
from app.db.projection_schema import ensure_projection_schema
from app.errors import unprocessable
from app.schemas.events import EventSearchItem


def _encode_cursor(updated_at: str, event_id: str) -> str:
    raw = json.dumps(["v1", updated_at, event_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    padding = "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode())
        if not isinstance(payload, list) or len(payload) != 3 or payload[0] != "v1":
            raise ValueError
        updated_at, event_id = payload[1], payload[2]
        if not isinstance(updated_at, str) or not isinstance(event_id, str) or not updated_at or not event_id:
            raise ValueError
        return updated_at, event_id
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise unprocessable("cursor is invalid or from an obsolete Event Search version") from exc


def _escape_like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


class EventSearchStore:
    """Search accessible Event history independently from the current Feed projection."""

    def __init__(self, database: Database) -> None:
        self._database = database
        ensure_projection_schema(database)

    def search(
        self,
        user_id: str,
        *,
        query: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[EventSearchItem], str | None]:
        normalized = " ".join(query.split())
        if len(normalized) > 100:
            raise unprocessable("q must be at most 100 characters")
        if limit < 1 or limit > 50:
            raise unprocessable("limit must be 1-50")

        cursor_updated_at = ""
        cursor_event_id = ""
        cursor_enabled = 0
        if cursor:
            cursor_updated_at, cursor_event_id = _decode_cursor(cursor)
            cursor_enabled = 1

        escaped = _escape_like(normalized.lower())
        pattern = f"%{escaped}%"
        now_epoch = int(time.time())
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.title,
                    e.summary,
                    e.current_phase,
                    e.current_summary,
                    e.updated_at,
                    CASE WHEN EXISTS (
                        SELECT 1
                        FROM event_follows f
                        WHERE f.user_id = ? AND f.event_id = e.id AND f.following = 1
                    ) THEN 1 ELSE 0 END AS following,
                    (
                        SELECT es2.publisher
                        FROM event_sources es2
                        WHERE es2.event_id = e.id
                        ORDER BY es2.published_at DESC, es2.id DESC
                        LIMIT 1
                    ) AS source_publisher
                FROM events e
                WHERE (
                    NOT EXISTS (
                        SELECT 1
                        FROM event_visibility v
                        WHERE v.event_id = e.id AND v.restricted = 1
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM event_user_access a
                        WHERE a.event_id = e.id
                          AND a.user_id = ?
                          AND a.expires_at > ?
                    )
                )
                  AND (
                    ? = ''
                    OR lower(e.title) LIKE ? ESCAPE '!'
                    OR lower(e.summary) LIKE ? ESCAPE '!'
                    OR lower(e.current_phase) LIKE ? ESCAPE '!'
                    OR lower(e.current_summary) LIKE ? ESCAPE '!'
                    OR EXISTS (
                        SELECT 1
                        FROM deltas d
                        WHERE d.event_id = e.id
                          AND d.active = 1
                          AND (
                            lower(d.summary) LIKE ? ESCAPE '!'
                            OR lower(d.before_text) LIKE ? ESCAPE '!'
                            OR lower(d.after_text) LIKE ? ESCAPE '!'
                          )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM event_sources es
                        WHERE es.event_id = e.id
                          AND (
                            lower(es.publisher) LIKE ? ESCAPE '!'
                            OR lower(es.title) LIKE ? ESCAPE '!'
                            OR lower(es.evidence) LIKE ? ESCAPE '!'
                          )
                    )
                  )
                  AND (
                    ? = 0
                    OR e.updated_at < ?
                    OR (e.updated_at = ? AND e.id < ?)
                  )
                ORDER BY e.updated_at DESC, e.id DESC
                LIMIT ?
                """,
                (
                    user_id,
                    user_id,
                    now_epoch,
                    normalized,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    cursor_enabled,
                    cursor_updated_at,
                    cursor_updated_at,
                    cursor_event_id,
                    limit + 1,
                ),
            ).fetchall()

        page_rows = rows[:limit]
        items = [
            EventSearchItem(
                id=row["id"],
                title=row["title"],
                summary=row["summary"],
                current_phase=row["current_phase"],
                current_summary=row["current_summary"],
                updated_at=row["updated_at"],
                following=bool(row["following"]),
                source_publisher=row["source_publisher"],
            )
            for row in page_rows
        ]
        next_cursor = None
        if len(rows) > limit and page_rows:
            last = page_rows[-1]
            next_cursor = _encode_cursor(last["updated_at"], last["id"])
        return items, next_cursor
