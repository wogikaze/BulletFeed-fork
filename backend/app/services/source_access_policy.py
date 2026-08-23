from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from app.database import Database

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 20
MAX_REQUESTS_PER_CLIENT_WINDOW = 20
MAX_REQUESTS_GLOBAL_PER_WINDOW = 200
MAX_ACTIVE_PER_USER = 2
MAX_ACTIVE_GLOBAL = 8
LEASE_TTL_SECONDS = 90
CACHE_TTL_SECONDS = 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_request_windows (
    user_id TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL,
    PRIMARY KEY(user_id, window_start)
);
CREATE TABLE IF NOT EXISTS source_client_request_windows (
    client_key TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL,
    PRIMARY KEY(client_key, window_start)
);
CREATE TABLE IF NOT EXISTS source_global_request_windows (
    window_start INTEGER PRIMARY KEY,
    request_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS source_request_leases (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_request_leases_user
ON source_request_leases(user_id, expires_at);
CREATE TABLE IF NOT EXISTS source_response_cache (
    cache_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
"""


@dataclass
class SourceLease:
    database: Database
    lease_id: str
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM source_request_leases WHERE id = ?",
                (self.lease_id,),
            )
        self.released = True

    def __enter__(self) -> SourceLease:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.release()


class SourceAccessPolicy:
    def __init__(self, database: Database) -> None:
        self._database = database
        with self._database.connect() as connection:
            connection.executescript(_SCHEMA)

    def acquire(
        self,
        user_id: str,
        *,
        client_key: str | None = None,
        now: int | None = None,
    ) -> SourceLease:
        current = int(time.time()) if now is None else now
        window_start = current - (current % WINDOW_SECONDS)
        lease_id = f"srclease_{secrets.token_urlsafe(12)}"
        stable_client_key = client_key or f"user_{user_id}"

        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM source_request_leases WHERE expires_at <= ?",
                (current,),
            )
            cutoff = window_start - WINDOW_SECONDS
            connection.execute(
                "DELETE FROM source_request_windows WHERE window_start < ?",
                (cutoff,),
            )
            connection.execute(
                "DELETE FROM source_client_request_windows WHERE window_start < ?",
                (cutoff,),
            )
            connection.execute(
                "DELETE FROM source_global_request_windows WHERE window_start < ?",
                (cutoff,),
            )

            user_count = self._scoped_count(
                connection,
                table="source_request_windows",
                key_column="user_id",
                key=user_id,
                window_start=window_start,
            )
            client_count = self._scoped_count(
                connection,
                table="source_client_request_windows",
                key_column="client_key",
                key=stable_client_key,
                window_start=window_start,
            )
            global_row = connection.execute(
                "SELECT request_count FROM source_global_request_windows WHERE window_start = ?",
                (window_start,),
            ).fetchone()
            global_count = int(global_row["request_count"]) if global_row is not None else 0
            if (
                user_count >= MAX_REQUESTS_PER_WINDOW
                or client_count >= MAX_REQUESTS_PER_CLIENT_WINDOW
                or global_count >= MAX_REQUESTS_GLOBAL_PER_WINDOW
            ):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Source request rate limit exceeded",
                )

            active_for_user = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM source_request_leases
                WHERE user_id = ? AND expires_at > ?
                """,
                (user_id, current),
            ).fetchone()["count"]
            active_global = connection.execute(
                "SELECT COUNT(*) AS count FROM source_request_leases WHERE expires_at > ?",
                (current,),
            ).fetchone()["count"]
            if active_for_user >= MAX_ACTIVE_PER_USER or active_global >= MAX_ACTIVE_GLOBAL:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many concurrent source requests",
                )

            self._increment_scoped_window(
                connection,
                table="source_request_windows",
                key_column="user_id",
                key=user_id,
                window_start=window_start,
            )
            self._increment_scoped_window(
                connection,
                table="source_client_request_windows",
                key_column="client_key",
                key=stable_client_key,
                window_start=window_start,
            )
            connection.execute(
                """
                INSERT INTO source_global_request_windows (window_start, request_count)
                VALUES (?, 1)
                ON CONFLICT(window_start) DO UPDATE SET
                    request_count = request_count + 1
                """,
                (window_start,),
            )
            connection.execute(
                """
                INSERT INTO source_request_leases (id, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (lease_id, user_id, current + LEASE_TTL_SECONDS, current),
            )
            connection.commit()
        return SourceLease(self._database, lease_id)

    @staticmethod
    def _scoped_count(
        connection,
        *,
        table: str,
        key_column: str,
        key: str,
        window_start: int,
    ) -> int:
        row = connection.execute(
            f"SELECT request_count FROM {table} WHERE {key_column} = ? AND window_start = ?",  # noqa: S608  # nosec B608
            (key, window_start),
        ).fetchone()
        return int(row["request_count"]) if row is not None else 0

    @staticmethod
    def _increment_scoped_window(
        connection,
        *,
        table: str,
        key_column: str,
        key: str,
        window_start: int,
    ) -> None:
        connection.execute(
            f"""
            INSERT INTO {table} ({key_column}, window_start, request_count)
            VALUES (?, ?, 1)
            ON CONFLICT({key_column}, window_start) DO UPDATE SET
                request_count = request_count + 1
            """,  # noqa: S608  # nosec B608
            (key, window_start),
        )

    def get_cached(self, namespace: str, arguments: Any, *, now: int | None = None) -> Any | None:
        current = int(time.time()) if now is None else now
        key = self.cache_key(namespace, arguments)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM source_response_cache
                WHERE cache_key = ? AND expires_at > ?
                """,
                (key, current),
            ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None

    def put_cached(
        self,
        namespace: str,
        arguments: Any,
        payload: Any,
        *,
        now: int | None = None,
    ) -> None:
        current = int(time.time()) if now is None else now
        key = self.cache_key(namespace, arguments)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_response_cache (cache_key, payload_json, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at
                """,
                (key, encoded, current + CACHE_TTL_SECONDS, current),
            )
            connection.execute(
                "DELETE FROM source_response_cache WHERE expires_at <= ?",
                (current,),
            )

    @staticmethod
    def cache_key(namespace: str, arguments: Any) -> str:
        canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(f"{namespace}|{canonical}".encode()).hexdigest()
        return f"srccache_{digest}"
