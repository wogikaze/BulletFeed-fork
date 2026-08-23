from __future__ import annotations

import time

from app.database import Database

_WORKER_HEARTBEAT_NAME = "source_sync"
_WORKER_HEARTBEAT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS worker_heartbeats (
    name TEXT PRIMARY KEY,
    heartbeat_at INTEGER NOT NULL,
    detail TEXT
)
"""


def _ensure_worker_heartbeat_table(connection) -> None:
    connection.execute(_WORKER_HEARTBEAT_TABLE_SQL)


def install_release_lifecycle_guards(database: Database, *, now: int | None = None) -> None:
    """Install invariant guards that must hold outside request-local code paths.

    Worker-side repository access loss is represented by selected=1 -> selected=0.
    That transition must also invalidate the user's GitHub credential state so the
    Android client can offer reauthorization instead of presenting a stale
    "connected" state. Source evidence is also fail-closed: a source kind cannot
    enter the public evidence table without a registered source policy.
    """
    current = int(time.time()) if now is None else now
    with database.connect() as connection:
        _ensure_worker_heartbeat_table(connection)
        connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS trg_github_watch_revocation_requires_reauth
            AFTER UPDATE OF selected ON github_repo_watches
            WHEN OLD.selected = 1 AND NEW.selected = 0
            BEGIN
                UPDATE users
                SET github_credential_state = 'reauthorization_required'
                WHERE id = NEW.user_id
                  AND github_user_id IS NOT NULL
                  AND github_credential_state = 'connected';
            END;

            CREATE TRIGGER IF NOT EXISTS trg_event_source_requires_policy
            BEFORE INSERT ON event_sources
            WHEN NOT EXISTS (
                SELECT 1 FROM source_policies WHERE source_kind = NEW.kind
            )
            BEGIN
                SELECT RAISE(ABORT, 'event source kind has no registered source policy');
            END;
            """
        )
        connection.execute(
            """
            UPDATE users
            SET github_credential_state = 'reauthorization_required'
            WHERE github_user_id IS NOT NULL
              AND github_credential_state = 'connected'
              AND NOT EXISTS (
                  SELECT 1
                  FROM github_connections c
                  WHERE c.github_user_id = users.github_user_id
                    AND c.github_token_encrypted IS NOT NULL
                    AND (c.token_expires_at IS NULL OR c.token_expires_at > ?)
              )
            """,
            (current,),
        )


def record_worker_heartbeat(
    database: Database,
    *,
    now: int | None = None,
    detail: str | None = None,
) -> None:
    current = int(time.time()) if now is None else now
    with database.connect() as connection:
        _ensure_worker_heartbeat_table(connection)
        connection.execute(
            """
            INSERT INTO worker_heartbeats (name, heartbeat_at, detail)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                heartbeat_at = excluded.heartbeat_at,
                detail = excluded.detail
            """,
            (_WORKER_HEARTBEAT_NAME, current, detail[:300] if detail else None),
        )


def worker_is_fresh(
    database: Database,
    *,
    now: int | None = None,
    max_age_seconds: int = 30,
) -> bool:
    current = int(time.time()) if now is None else now
    with database.connect() as connection:
        _ensure_worker_heartbeat_table(connection)
        row = connection.execute(
            "SELECT heartbeat_at FROM worker_heartbeats WHERE name = ?",
            (_WORKER_HEARTBEAT_NAME,),
        ).fetchone()
    return row is not None and current - int(row["heartbeat_at"]) <= max_age_seconds
