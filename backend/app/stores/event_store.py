from __future__ import annotations

import re
import sqlite3

from fastapi import HTTPException, status

from app.database import Database
from app.db.projection_schema import ensure_projection_schema
from app.schemas.common import CurrentState, Delta, Impact, SourceEvidence, TimelineEntry
from app.schemas.events import EventDetail, UnknownFact
from app.services.event_access import user_can_access_event
from app.services.follow_baseline import SUBJECT_EVENT, record_follow_baseline
from app.services.knowledge_evidence import CONFIDENCE_HIGH, STATE_KNOWN, replay_knowledge_state

_FACT_SENTENCE = re.compile(r"(?<=[。．！？])|(?<=[.!?])(?:\s+|$)")
_MAX_FACT_BULLETS = 8
_MAX_FACT_CHARS = 400
_MIN_FACT_CHARS = 8


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


def _fact_texts(detail: str, value: str) -> tuple[str, ...]:
    raw = (detail or "").strip() or (value or "").strip()
    if not raw:
        return ()
    parts = [part.strip(" \t\r\n-•") for part in _FACT_SENTENCE.split(raw)]
    bullets = [part for part in parts if len(part) >= _MIN_FACT_CHARS]
    if len(bullets) >= 2:
        return tuple(item[:_MAX_FACT_CHARS] for item in bullets[:_MAX_FACT_BULLETS])
    return (raw[:_MAX_FACT_CHARS],)


def _claim_is_explicitly_known(connection: sqlite3.Connection, *, user_id: str, claim_id: str) -> bool:
    derived = replay_knowledge_state(connection, user_id=user_id, claim_id=claim_id)
    return derived.state == STATE_KNOWN and derived.confidence == CONFIDENCE_HIGH


def _unknown_facts_for_event(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    event_id: str,
) -> list[UnknownFact]:
    rows = connection.execute(
        """
        SELECT id, slot, value_text, detail_text, valid_at
        FROM state_claims
        WHERE event_id = ?
        ORDER BY slot ASC, valid_at DESC, id DESC
        """,
        (event_id,),
    ).fetchall()
    latest_by_slot: dict[str, sqlite3.Row] = {}
    for row in rows:
        slot = str(row["slot"])
        if slot not in latest_by_slot:
            latest_by_slot[slot] = row
    facts: list[UnknownFact] = []
    seen: set[str] = set()
    for row in latest_by_slot.values():
        claim_id = str(row["id"])
        if _claim_is_explicitly_known(connection, user_id=user_id, claim_id=claim_id):
            continue
        for index, text in enumerate(_fact_texts(str(row["detail_text"]), str(row["value_text"]))):
            if text in seen:
                continue
            seen.add(text)
            facts.append(UnknownFact(id=f"{claim_id}:{index}", text=text))
            if len(facts) >= _MAX_FACT_BULLETS:
                return facts
    return facts


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
            unknown_facts = _unknown_facts_for_event(
                connection,
                user_id=user_id,
                event_id=event_id,
            )
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
            unknown_facts=unknown_facts,
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
