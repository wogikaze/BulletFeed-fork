from __future__ import annotations

import time

from app.database import Database

PRIVATE_EVENT_ACCESS_TTL_SECONDS = 10 * 60


def project_repository_event_access(
    database: Database,
    *,
    repository_key: str,
    event_id: str,
    now: int | None = None,
) -> list[str]:
    """Persist fail-closed visibility for repository-scoped events.

    Public repositories remain visible to authenticated users. Private repository
    events require a short-lived per-user grant refreshed by the sync pipeline.
    """
    current = int(time.time()) if now is None else now
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT user_id, private
            FROM github_repo_watches
            WHERE full_name = ? AND selected = 1
            ORDER BY user_id
            """,
            (repository_key,),
        ).fetchall()
        user_ids = [row["user_id"] for row in rows]
        restricted = any(bool(row["private"]) for row in rows)
        connection.execute(
            """
            INSERT INTO event_visibility (event_id, restricted)
            VALUES (?, ?)
            ON CONFLICT(event_id) DO UPDATE SET restricted = excluded.restricted
            """,
            (event_id, int(restricted)),
        )
        if not restricted:
            connection.execute("DELETE FROM event_user_access WHERE event_id = ?", (event_id,))
            return user_ids

        expires_at = current + PRIVATE_EVENT_ACCESS_TTL_SECONDS
        connection.execute(
            "DELETE FROM event_user_access WHERE event_id = ? AND expires_at <= ?",
            (event_id, current),
        )
        selected = set(user_ids)
        existing = connection.execute(
            "SELECT user_id FROM event_user_access WHERE event_id = ?",
            (event_id,),
        ).fetchall()
        for row in existing:
            if row["user_id"] not in selected:
                connection.execute(
                    "DELETE FROM event_user_access WHERE event_id = ? AND user_id = ?",
                    (event_id, row["user_id"]),
                )
        for user_id in user_ids:
            connection.execute(
                """
                INSERT INTO event_user_access (event_id, user_id, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(event_id, user_id) DO UPDATE SET expires_at = excluded.expires_at
                """,
                (event_id, user_id, expires_at),
            )
        return user_ids


def user_can_access_event(
    connection,
    *,
    user_id: str,
    event_id: str,
    now: int | None = None,
) -> bool:
    current = int(time.time()) if now is None else now
    visibility = connection.execute(
        "SELECT restricted FROM event_visibility WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    if visibility is None or not bool(visibility["restricted"]):
        return True
    grant = connection.execute(
        """
        SELECT 1
        FROM event_user_access
        WHERE event_id = ? AND user_id = ? AND expires_at > ?
        """,
        (event_id, user_id, current),
    ).fetchone()
    return grant is not None


def revoke_repository_access(database: Database, *, user_id: str, repository_key: str) -> None:
    """Remove every user-facing projection tied to a repository the user can no longer access."""
    with database.connect() as connection:
        event_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM ledger_events WHERE source_key = ?",
                (repository_key,),
            ).fetchall()
        ]
        for event_id in event_ids:
            connection.execute(
                "DELETE FROM event_user_access WHERE event_id = ? AND user_id = ?",
                (event_id, user_id),
            )
            connection.execute(
                "UPDATE feed_items SET dismissed = 1 WHERE event_id = ? AND user_id = ?",
                (event_id, user_id),
            )
            connection.execute(
                "DELETE FROM event_follows WHERE event_id = ? AND user_id = ?",
                (event_id, user_id),
            )

        alert_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM security_alerts WHERE user_id = ? AND repository_full_name = ?",
                (user_id, repository_key),
            ).fetchall()
        ]
        for alert_id in alert_ids:
            connection.execute(
                "DELETE FROM notifications WHERE user_id = ? AND target_id = ?",
                (user_id, alert_id),
            )
        connection.execute(
            "DELETE FROM security_alerts WHERE user_id = ? AND repository_full_name = ?",
            (user_id, repository_key),
        )
