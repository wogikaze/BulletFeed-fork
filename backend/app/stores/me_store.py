from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.database import Database
from app.errors import not_found, unprocessable
from app.schemas.me import MeBootstrap, Profile, Topic

_MIN_TOPICS = 5
_MAX_TOPICS = 20


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _topic_from_row(row) -> Topic:
    return Topic(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        priority=row["priority"],
        order=row["sort_order"],
        created_at=_iso(row["created_at"]),
    )


class MeStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get_profile(self, user_id: str) -> Profile:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return Profile(occupation="", interests=[], region="")
        return Profile(
            occupation=row["occupation"],
            interests=json.loads(row["interests_json"]),
            region=row["region"],
        )

    def save_profile(self, user_id: str, occupation: str, interests: list[str], region: str) -> Profile:
        now = int(time.time())
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO profiles (user_id, occupation, interests_json, region, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    occupation = excluded.occupation,
                    interests_json = excluded.interests_json,
                    region = excluded.region,
                    updated_at = excluded.updated_at
                """,
                (user_id, occupation, json.dumps(interests), region, now),
            )
        return Profile(occupation=occupation, interests=interests, region=region)

    def bootstrap(self, user_id: str, github_connected: bool, onboarding_completed: bool) -> MeBootstrap:
        with self._database.connect() as connection:
            topic_count = connection.execute(
                "SELECT COUNT(*) AS count FROM topics WHERE user_id = ?",
                (user_id,),
            ).fetchone()["count"]
        return MeBootstrap(
            onboarding_completed=onboarding_completed,
            profile=self.get_profile(user_id),
            topic_count=topic_count,
            github_connected=github_connected,
        )

    def list_topics(self, user_id: str) -> list[Topic]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM topics WHERE user_id = ? ORDER BY sort_order ASC, created_at ASC",
                (user_id,),
            ).fetchall()
        return [_topic_from_row(row) for row in rows]

    def add_topic(self, user_id: str, name: str, topic_type: str) -> Topic:
        cleaned = name.strip()
        if not cleaned:
            raise unprocessable("topic name is required")
        with self._database.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM topics WHERE user_id = ?",
                (user_id,),
            ).fetchone()["count"]
            if count >= _MAX_TOPICS:
                raise unprocessable("topic limit reached")
            existing = connection.execute(
                "SELECT id FROM topics WHERE user_id = ? AND lower(name) = lower(?)",
                (user_id, cleaned),
            ).fetchone()
            if existing is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="topic already exists")
            now = int(time.time())
            topic_id = f"topic_{secrets.token_urlsafe(8)}"
            connection.execute(
                """
                INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
                VALUES (?, ?, ?, ?, 'normal', ?, ?)
                """,
                (topic_id, user_id, cleaned, topic_type, count, now),
            )
            row = connection.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return _topic_from_row(row)

    def delete_topic(self, user_id: str, topic_id: str) -> None:
        with self._database.connect() as connection:
            changed = connection.execute(
                "DELETE FROM topics WHERE id = ? AND user_id = ?",
                (topic_id, user_id),
            ).rowcount
        if changed == 0:
            raise not_found("Topic was not found")

    def patch_topic(self, user_id: str, topic_id: str, priority: str | None, order: int | None) -> Topic:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM topics WHERE id = ? AND user_id = ?",
                (topic_id, user_id),
            ).fetchone()
            if row is None:
                raise not_found("Topic was not found")
            next_priority = priority or row["priority"]
            next_order = row["sort_order"] if order is None else order
            connection.execute(
                "UPDATE topics SET priority = ?, sort_order = ? WHERE id = ? AND user_id = ?",
                (next_priority, next_order, topic_id, user_id),
            )
            updated = connection.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return _topic_from_row(updated)

    def search_topics(self, query: str) -> list[Topic]:
        needle = f"%{query.strip()}%"
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, type, 'normal' AS priority, 0 AS sort_order, 0 AS created_at
                FROM topic_catalog
                WHERE name LIKE ? COLLATE NOCASE
                ORDER BY name ASC
                LIMIT 20
                """,
                (needle,),
            ).fetchall()
        return [_topic_from_row(row) for row in rows]

    def complete_onboarding(
        self,
        user_id: str,
        occupation: str,
        interests: list[str],
        region: str,
        topics: list[str],
        connect_github: bool,
    ) -> dict:
        unique_topics = []
        seen: set[str] = set()
        for name in topics:
            cleaned = name.strip()
            if not cleaned or cleaned.lower() in seen:
                continue
            seen.add(cleaned.lower())
            unique_topics.append(cleaned)
        if len(unique_topics) < _MIN_TOPICS:
            raise unprocessable("at least 5 topics are required")
        if len(unique_topics) > _MAX_TOPICS:
            raise unprocessable("topic limit reached")
        self.save_profile(user_id, occupation, interests, region)
        now = int(time.time())
        with self._database.connect() as connection:
            connection.execute("DELETE FROM topics WHERE user_id = ?", (user_id,))
            for index, name in enumerate(unique_topics):
                connection.execute(
                    """
                    INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
                    VALUES (?, ?, ?, 'technology', 'normal', ?, ?)
                    """,
                    (f"topic_{secrets.token_urlsafe(8)}", user_id, name, index, now),
                )
            connection.execute(
                "UPDATE users SET onboarding_completed = 1, github_connected = ? WHERE id = ?",
                (int(connect_github), user_id),
            )
        return {
            "completed": True,
            "github_authorization": {
                "required": connect_github,
                "authorization_url": None,
            },
        }
