from __future__ import annotations

from collections.abc import Sequence

from app.database import Database
from app.services.feed_projection import project_event_for_audience


def upsert_source_subscription(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    selected: int = 1,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_sync_subscriptions (source_type, source_key, selected)
            VALUES (?, ?, ?)
            ON CONFLICT(source_type, source_key) DO UPDATE SET selected = excluded.selected
            """,
            (source_type, source_key, selected),
        )


def add_subscription_user(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    user_id: str,
) -> None:
    upsert_source_subscription(
        database,
        source_type=source_type,
        source_key=source_key,
        selected=1,
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_sync_subscription_users (source_type, source_key, user_id)
            VALUES (?, ?, ?)
            ON CONFLICT(source_type, source_key, user_id) DO NOTHING
            """,
            (source_type, source_key, user_id),
        )


def list_subscription_user_ids(
    database: Database,
    *,
    source_type: str,
    source_keys: Sequence[str],
) -> tuple[str, ...]:
    keys = tuple(dict.fromkeys(key for key in source_keys if key))
    if not keys:
        return ()
    user_ids: list[str] = []
    with database.connect() as connection:
        for source_key in keys:
            rows = connection.execute(
                """
                SELECT users.user_id
                FROM source_sync_subscription_users AS users
                JOIN source_sync_subscriptions AS subscriptions
                  ON subscriptions.source_type = users.source_type
                 AND subscriptions.source_key = users.source_key
                WHERE users.source_type = ?
                  AND users.source_key = ?
                  AND subscriptions.selected = 1
                ORDER BY users.user_id
                """,
                (source_type, source_key),
            ).fetchall()
            user_ids.extend(row["user_id"] for row in rows)
    return tuple(sorted(dict.fromkeys(user_ids)))


def project_events_for_subscription_audience(
    database: Database,
    *,
    source_type: str,
    source_keys: Sequence[str],
    event_ids: Sequence[str],
) -> None:
    user_ids = list_subscription_user_ids(
        database,
        source_type=source_type,
        source_keys=source_keys,
    )
    for event_id in event_ids:
        project_event_for_audience(database, event_id=event_id, user_ids=user_ids)
