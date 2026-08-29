from __future__ import annotations

import sqlite3

from fastapi import HTTPException, status

from app.database import Database
from app.db.projection_schema import ensure_projection_schema
from app.schemas.common import CurrentState, Delta, Impact, SourceEvidence, TimelineEntry
from app.schemas.events import EventDetail
from app.services.event_access import user_can_access_event
from app.services.follow_baseline import SUBJECT_EVENT, record_follow_baseline


def _delta_from_row(row: sqlite3.Row) -> Delta:
    return Delta(
        id=row["id"],
        type=row["type"],
        summary=row["summary"],
        before=row["before_text"],
        after=row["after_text"],
        occurred_at=row["occurred_at"],
    )


def _timeline_state(row: sqlite3.Row) -> dict[str, str] | None:
    state = {
        key: value
        for key, value in (
            ("before", row["state_before"]),
            ("after", row["state_after"]),
        )
        if value is not None
    }
    return state or None


class EventStore:
    def __init__(self, database: Database) -> None:
        self._database = database
        ensure_projection_schema(database)

    def get_event(self, user_id: str, event_id: str, from_feed_item: str | None) -> EventDetail:
        with self._database.connect() as connection:
            event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if event is None or not user_can_access_event(
                connection,
                user_id=user_id,
                event_id=event_id,
            ):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event was not found")
            deltas = connection.execute(
                """
                SELECT * FROM deltas
                WHERE event_id = ? AND active = 1
                ORDER BY occurred_at DESC, id DESC
                """,
                (event_id,),
            ).fetchall()
            if not deltas:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event was not found")
            latest = _delta_from_row(deltas[0])
            opened = None
            if from_feed_item:
                feed_row = connection.execute(
                    """
                    SELECT d.* FROM feed_items f
                    JOIN deltas d ON d.id = f.delta_id
                    WHERE f.id = ? AND f.user_id = ? AND f.event_id = ?
                    """,
                    (from_feed_item, user_id, event_id),
                ).fetchone()
                if feed_row is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event was not found")
                opened = _delta_from_row(feed_row)
            follow = connection.execute(
                "SELECT following FROM event_follows WHERE user_id = ? AND event_id = ?",
                (user_id, event_id),
            ).fetchone()
            timeline_rows = connection.execute(
                "SELECT * FROM event_timeline WHERE event_id = ? ORDER BY occurred_at ASC, id ASC",
                (event_id,),
            ).fetchall()
            impact_rows = connection.execute(
                "SELECT * FROM event_impacts WHERE event_id = ?",
                (event_id,),
            ).fetchall()
            source_rows = connection.execute(
                "SELECT * FROM event_sources WHERE event_id = ?",
                (event_id,),
            ).fetchall()
        return EventDetail(
            id=event["id"],
            title=event["title"],
            summary=event["summary"],
            current_state=CurrentState(
                phase=event["current_phase"],
                summary=event["current_summary"],
                since=event["current_since"],
                confidence=event["current_confidence"],
            ),
            latest_delta=latest,
            opened_delta=opened,
            timeline=[
                TimelineEntry(
                    id=row["id"],
                    type=row["type"],
                    occurred_at=row["occurred_at"],
                    title=row["title"],
                    description=row["description"],
                    delta_id=row["delta_id"],
                    state=_timeline_state(row),
                )
                for row in timeline_rows
            ],
            impacts=[
                Impact(kind=row["kind"], text=row["text"], confidence=row["confidence"])
                for row in impact_rows
            ],
            sources=[
                SourceEvidence(
                    publisher=row["publisher"],
                    kind=row["kind"],
                    title=row["title"],
                    url=row["url"],
                    published_at=row["published_at"],
                    retrieved_at=row["retrieved_at"],
                    evidence=row["evidence"],
                )
                for row in source_rows
            ],
            following=bool(follow["following"]) if follow is not None else False,
        )

    def set_following(
        self,
        user_id: str,
        event_id: str,
        following: bool,
        *,
        catch_up: bool = False,
        followed_at: int | None = None,
    ) -> dict:
        with self._database.connect() as connection:
            event = connection.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
            if event is None or not user_can_access_event(
                connection,
                user_id=user_id,
                event_id=event_id,
            ):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event was not found")
            previous = connection.execute(
                "SELECT following FROM event_follows WHERE user_id = ? AND event_id = ?",
                (user_id, event_id),
            ).fetchone()
            was_following = bool(previous["following"]) if previous is not None else False
            connection.execute(
                """
                INSERT INTO event_follows (user_id, event_id, following)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, event_id) DO UPDATE SET following = excluded.following
                """,
                (user_id, event_id, int(following)),
            )
            if following and not was_following:
                record_follow_baseline(
                    connection,
                    user_id=user_id,
                    subject_kind=SUBJECT_EVENT,
                    subject_id=event_id,
                    catch_up=catch_up,
                    followed_at=followed_at,
                )
        return {"event_id": event_id, "following": following}
