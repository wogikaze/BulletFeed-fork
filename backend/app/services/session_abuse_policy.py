from __future__ import annotations

import time

from fastapi import HTTPException, status

from app.database import Database

SESSION_WINDOW_SECONDS = 60
MAX_SESSIONS_PER_CLIENT_WINDOW = 10
MAX_SESSIONS_GLOBAL_PER_WINDOW = 100
EMPTY_ANONYMOUS_RETENTION_SECONDS = 24 * 60 * 60
MAX_GC_USERS_PER_REQUEST = 100
_GLOBAL_SCOPE = "global"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS anonymous_session_request_windows (
    scope_key TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL,
    PRIMARY KEY(scope_key, window_start)
);
"""

_USER_DATA_TABLES = (
    "user_claim_exposures",
    "exposures",
    "feedback",
    "event_follows",
    "event_user_access",
    "notifications",
    "security_alerts",
    "deliveries",
    "feed_items",
    "github_repo_watches",
    "topics",
)


class SessionCreationPolicy:
    def __init__(self, database: Database) -> None:
        self._database = database
        with self._database.connect() as connection:
            connection.executescript(_SCHEMA)

    def consume(self, client_key: str, *, now: int | None = None) -> None:
        current = int(time.time()) if now is None else now
        window_start = current - (current % SESSION_WINDOW_SECONDS)

        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_empty_anonymous_users(connection, current)
            connection.execute(
                "DELETE FROM anonymous_session_request_windows WHERE window_start < ?",
                (window_start - SESSION_WINDOW_SECONDS,),
            )
            global_count = self._count(connection, _GLOBAL_SCOPE, window_start)
            if global_count >= MAX_SESSIONS_GLOBAL_PER_WINDOW:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Anonymous session creation rate limit exceeded",
                )
            client_count = self._count(connection, client_key, window_start)
            if client_count >= MAX_SESSIONS_PER_CLIENT_WINDOW:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Anonymous session creation rate limit exceeded",
                )
            self._increment(connection, _GLOBAL_SCOPE, window_start)
            self._increment(connection, client_key, window_start)
            connection.commit()

    @staticmethod
    def _count(connection, scope_key: str, window_start: int) -> int:
        row = connection.execute(
            """
            SELECT request_count
            FROM anonymous_session_request_windows
            WHERE scope_key = ? AND window_start = ?
            """,
            (scope_key, window_start),
        ).fetchone()
        return int(row["request_count"]) if row is not None else 0

    @staticmethod
    def _increment(connection, scope_key: str, window_start: int) -> None:
        connection.execute(
            """
            INSERT INTO anonymous_session_request_windows (scope_key, window_start, request_count)
            VALUES (?, ?, 1)
            ON CONFLICT(scope_key, window_start) DO UPDATE SET
                request_count = request_count + 1
            """,
            (scope_key, window_start),
        )

    @staticmethod
    def _prune_empty_anonymous_users(connection, now: int) -> None:
        cutoff = now - EMPTY_ANONYMOUS_RETENTION_SECONDS
        candidates = connection.execute(
            """
            SELECT u.id
            FROM users u
            LEFT JOIN profiles p ON p.user_id = u.id
            WHERE u.created_at <= ?
              AND u.onboarding_completed = 0
              AND u.github_user_id IS NULL
              AND (
                  p.user_id IS NULL
                  OR (p.occupation = '' AND p.interests_json = '[]' AND p.region = '')
              )
            ORDER BY u.created_at ASC
            LIMIT ?
            """,
            (cutoff, MAX_GC_USERS_PER_REQUEST),
        ).fetchall()
        for candidate in candidates:
            user_id = str(candidate["id"])
            oauth_flow = connection.execute(
                "SELECT 1 FROM oauth_flows WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
            if oauth_flow is not None:
                continue
            if any(
                connection.execute(
                    f"SELECT 1 FROM {table} WHERE user_id = ? LIMIT 1",  # noqa: S608  # nosec B608
                    (user_id,),
                ).fetchone()
                is not None
                for table in _USER_DATA_TABLES
            ):
                continue
            connection.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM user_refresh_tokens WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
