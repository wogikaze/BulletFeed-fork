from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.database import Database
from app.errors import not_found, unprocessable
from app.schemas.common import TopicType
from app.schemas.me import MeBootstrap, Profile, Topic, TopicRecommendationItem, TopicRecommendationList
from app.services.feed_projection import FeedProjector
from app.services.topic_recommendations import recommend_topics_for_user

_MIN_TOPICS = 5
_MAX_TOPICS = 20


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _topic_type(value: str) -> TopicType:
    if value in {"technology", "service", "company"}:
        return value
    return "technology"


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
        self._projector = FeedProjector(database)

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
        self._projector.reproject_user(user_id=user_id)
        return Profile(occupation=occupation, interests=interests, region=region)

    def bootstrap(self, user_id: str) -> MeBootstrap:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT onboarding_completed, onboarding_state, github_connected
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                raise not_found("User was not found")
            topic_count = connection.execute(
                "SELECT COUNT(*) AS count FROM topics WHERE user_id = ?",
                (user_id,),
            ).fetchone()["count"]
        return MeBootstrap(
            onboarding_completed=bool(row["onboarding_completed"]),
            onboarding_state=row["onboarding_state"],
            profile=self.get_profile(user_id),
            topic_count=topic_count,
            github_connected=bool(row["github_connected"]),
        )

    def list_topics(self, user_id: str) -> list[Topic]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM topics WHERE user_id = ? ORDER BY sort_order ASC, created_at ASC",
                (user_id,),
            ).fetchall()
        return [_topic_from_row(row) for row in rows]

    def add_topic(
        self,
        user_id: str,
        name: str,
        topic_type: str,
        *,
        reproject: bool = True,
    ) -> Topic:
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
        if reproject:
            self._projector.reproject_user(user_id=user_id)
        return _topic_from_row(row)

    def delete_topic(self, user_id: str, topic_id: str) -> None:
        with self._database.connect() as connection:
            changed = connection.execute(
                "DELETE FROM topics WHERE id = ? AND user_id = ?",
                (topic_id, user_id),
            ).rowcount
        if changed == 0:
            raise not_found("Topic was not found")
        self._projector.reproject_user(user_id=user_id)

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
        self._projector.reproject_user(user_id=user_id)
        return _topic_from_row(updated)

    def list_topic_recommendations(
        self,
        user_id: str,
        *,
        limit: int = 10,
        include_followed: bool = True,
    ) -> TopicRecommendationList:
        with self._database.connect() as connection:
            result = recommend_topics_for_user(
                connection,
                user_id,
                limit=limit,
                include_followed=include_followed,
            )
        return TopicRecommendationList(
            version=result.version,
            items=[
                TopicRecommendationItem(
                    id=item.topic_id,
                    name=item.name,
                    type=_topic_type(item.topic_type),
                    score=item.score,
                    reason=item.reason,
                    provenance=item.provenance,
                    already_followed=item.already_followed,
                    confidence=item.confidence,
                    source_signals=list(item.source_signals),
                )
                for item in result.items
            ],
        )

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
        unique_topics: list[str] = []
        seen: set[str] = set()
        for name in topics:
            cleaned = name.strip()
            if not cleaned or cleaned.lower() in seen:
                continue
            seen.add(cleaned.lower())
            unique_topics.append(cleaned)
        if not connect_github and len(unique_topics) < _MIN_TOPICS:
            raise unprocessable("at least 5 topics are required unless GitHub import is enabled")
        if len(unique_topics) > _MAX_TOPICS:
            raise unprocessable("topic limit reached")

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
            connection.execute("DELETE FROM topics WHERE user_id = ?", (user_id,))
            for index, name in enumerate(unique_topics):
                catalog = connection.execute(
                    "SELECT name, type FROM topic_catalog WHERE lower(name) = lower(?) LIMIT 1",
                    (name,),
                ).fetchone()
                stored_name = catalog["name"] if catalog is not None else name
                topic_type = catalog["type"] if catalog is not None else "technology"
                connection.execute(
                    """
                    INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
                    VALUES (?, ?, ?, ?, 'normal', ?, ?)
                    """,
                    (f"topic_{secrets.token_urlsafe(8)}", user_id, stored_name, topic_type, index, now),
                )
            next_state = "github_pending" if connect_github else "ready"
            connection.execute(
                """
                UPDATE users
                SET onboarding_completed = ?, onboarding_state = ?
                WHERE id = ?
                """,
                (int(next_state == "ready"), next_state, user_id),
            )
        self._projector.reproject_user(user_id=user_id)
        return {
            "completed": next_state == "ready",
            "state": next_state,
            "github_authorization": {
                "required": connect_github,
                "authorization_url": None,
            },
        }

    def mark_repository_setup_ready(self, user_id: str) -> None:
        with self._database.connect() as connection:
            selected = connection.execute(
                """
                SELECT 1 FROM github_repo_watches
                WHERE user_id = ? AND selected = 1 LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if selected is None:
                raise unprocessable("select at least one GitHub repository to finish setup")
            connection.execute(
                """
                UPDATE users
                SET onboarding_completed = 1, onboarding_state = 'ready'
                WHERE id = ?
                """,
                (user_id,),
            )
        self._projector.reproject_user(user_id=user_id)

    def delete_account(self, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = connection.execute(
                "SELECT github_user_id FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                connection.rollback()
                raise not_found("User was not found")
            github_user_id = user["github_user_id"]
            connection.execute("UPDATE oauth_flows SET user_id = NULL WHERE user_id = ?", (user_id,))
            for table in (
                "user_knowledge_evidence",
                "user_knowledge_signals",
                "user_claim_exposures",
                "exposures",
                "user_ranking_features",
                "user_ranking_resets",
                "feedback",
                "event_follows",
                "event_user_access",
                "notifications",
                "security_alerts",
                "deliveries",
                "feed_items",
                "github_repo_watches",
                "topics",
                "profiles",
                "user_sessions",
                "user_refresh_tokens",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE user_id = ?",  # nosec B608
                    (user_id,),
                )
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if github_user_id is not None:
                remaining = connection.execute(
                    "SELECT 1 FROM users WHERE github_user_id = ? LIMIT 1",
                    (github_user_id,),
                ).fetchone()
                if remaining is None:
                    connection.execute(
                        "DELETE FROM github_connections WHERE github_user_id = ?",
                        (github_user_id,),
                    )
            connection.commit()
