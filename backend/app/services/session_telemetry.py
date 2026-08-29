"""Privacy-conscious feed-session outcome telemetry (Eval-04).

Separate from Event / Claim / Delta / Observation. Missing or disabled
telemetry never changes the factual ledger. Raw scroll coordinates are
not stored. GET /feed does not start a session.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.config import Settings, get_settings
from app.db.session_telemetry_schema import SESSION_TELEMETRY_TABLES
from app.services.feedback_signals import ledger_world_state

POLICY_VERSION: Final = "session-telemetry-v1"
RETENTION_DAYS: Final = 30

KIND_SESSION_START: Final = "session_start"
KIND_CARD_DISPLAYED: Final = "card_displayed"
KIND_DETAIL_READ: Final = "detail_read"
KIND_FEEDBACK: Final = "feedback"
KIND_FOLLOW: Final = "follow"
KIND_SESSION_END: Final = "session_end"

OUTCOME_KINDS: Final[frozenset[str]] = frozenset(
    {
        KIND_SESSION_START,
        KIND_CARD_DISPLAYED,
        KIND_DETAIL_READ,
        KIND_FEEDBACK,
        KIND_FOLLOW,
        KIND_SESSION_END,
    }
)
USEFUL_FEEDBACK: Final[frozenset[str]] = frozenset({"important", "learned_now"})
RESHOWN_FEEDBACK: Final[frozenset[str]] = frozenset({"already_knew"})


@dataclass(frozen=True)
class FeedSession:
    id: str
    user_id: str
    started_at: int
    ended_at: int | None


@dataclass(frozen=True)
class SessionOutcome:
    id: str
    user_id: str
    session_id: str
    kind: str
    feed_item_id: str | None
    feedback_type: str | None
    created_at: int


@dataclass(frozen=True)
class SessionMetrics:
    version: str
    session_count: int
    displayed_count: int
    useful_card_rate: float | None
    already_known_reshow_rate: float | None
    cards_to_useful_item: float | None
    feedback_response_rate: float | None


def telemetry_enabled(settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    return bool(current.session_telemetry_enabled)


def start_feed_session(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    session_id: str | None = None,
    created_at: int | None = None,
    settings: Settings | None = None,
) -> FeedSession | None:
    if not telemetry_enabled(settings):
        return None
    at = int(time.time()) if created_at is None else created_at
    sid = session_id or f"fs_{secrets.token_urlsafe(8)}"
    connection.execute(
        """
        INSERT INTO feed_sessions (id, user_id, started_at, ended_at)
        VALUES (?, ?, ?, NULL)
        """,
        (sid, user_id, at),
    )
    _insert_outcome(
        connection,
        user_id=user_id,
        session_id=sid,
        kind=KIND_SESSION_START,
        created_at=at,
    )
    return FeedSession(id=sid, user_id=user_id, started_at=at, ended_at=None)


def open_session_id(connection: sqlite3.Connection, *, user_id: str) -> str | None:
    row = connection.execute(
        """
        SELECT id FROM feed_sessions
        WHERE user_id = ? AND ended_at IS NULL
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return str(row["id"]) if row is not None else None


def record_session_outcome(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    kind: str,
    feed_item_id: str | None = None,
    feedback_type: str | None = None,
    session_id: str | None = None,
    created_at: int | None = None,
    settings: Settings | None = None,
) -> SessionOutcome | None:
    """Append one outcome. No-op when disabled or no open session."""
    if not telemetry_enabled(settings):
        return None
    if kind not in OUTCOME_KINDS:
        raise ValueError(f"unsupported session outcome kind: {kind}")
    sid = session_id or open_session_id(connection, user_id=user_id)
    if sid is None:
        return None
    at = int(time.time()) if created_at is None else created_at
    return _insert_outcome(
        connection,
        user_id=user_id,
        session_id=sid,
        kind=kind,
        feed_item_id=feed_item_id,
        feedback_type=feedback_type,
        created_at=at,
    )


def end_feed_session(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    session_id: str | None = None,
    created_at: int | None = None,
    settings: Settings | None = None,
) -> FeedSession | None:
    if not telemetry_enabled(settings):
        return None
    sid = session_id or open_session_id(connection, user_id=user_id)
    if sid is None:
        return None
    at = int(time.time()) if created_at is None else created_at
    updated = connection.execute(
        """
        UPDATE feed_sessions
        SET ended_at = COALESCE(ended_at, ?)
        WHERE id = ? AND user_id = ?
        """,
        (at, sid, user_id),
    ).rowcount
    if updated == 0:
        return None
    row = connection.execute(
        """
        SELECT id, user_id, started_at, ended_at
        FROM feed_sessions
        WHERE id = ? AND user_id = ?
        """,
        (sid, user_id),
    ).fetchone()
    if row is None:
        return None
    _insert_outcome(
        connection,
        user_id=user_id,
        session_id=sid,
        kind=KIND_SESSION_END,
        created_at=at,
    )
    return FeedSession(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        started_at=int(row["started_at"]),
        ended_at=int(row["ended_at"]) if row["ended_at"] is not None else at,
    )


def list_session_outcomes(connection: sqlite3.Connection, *, user_id: str) -> tuple[SessionOutcome, ...]:
    rows = connection.execute(
        """
        SELECT id, user_id, session_id, kind, feed_item_id, feedback_type, created_at
        FROM feed_session_outcomes
        WHERE user_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (user_id,),
    ).fetchall()
    return tuple(
        SessionOutcome(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            session_id=str(row["session_id"]),
            kind=str(row["kind"]),
            feed_item_id=row["feed_item_id"],
            feedback_type=row["feedback_type"],
            created_at=int(row["created_at"]),
        )
        for row in rows
    )


def summarize_session_metrics(
    outcomes: Sequence[SessionOutcome],
) -> SessionMetrics:
    sessions = {row.session_id for row in outcomes if row.kind == KIND_SESSION_START}
    displayed = [row for row in outcomes if row.kind == KIND_CARD_DISPLAYED]
    feedback = [row for row in outcomes if row.kind == KIND_FEEDBACK]
    useful = [row for row in feedback if row.feedback_type in USEFUL_FEEDBACK]
    reshown = [row for row in feedback if row.feedback_type in RESHOWN_FEEDBACK]
    displayed_count = len(displayed)
    useful_rate = (len(useful) / displayed_count) if displayed_count else None
    reshow_rate = (len(reshown) / displayed_count) if displayed_count else None
    response_rate = (len(feedback) / displayed_count) if displayed_count else None
    first_useful_at: list[int] = []
    by_session: dict[str, list[SessionOutcome]] = {}
    for row in outcomes:
        by_session.setdefault(row.session_id, []).append(row)
    for rows in by_session.values():
        cards = 0
        found = None
        for row in rows:
            if row.kind == KIND_CARD_DISPLAYED:
                cards += 1
            if row.kind == KIND_FEEDBACK and row.feedback_type in USEFUL_FEEDBACK:
                found = cards or 1
                break
        if found is not None:
            first_useful_at.append(found)
    cards_to_useful = (sum(first_useful_at) / len(first_useful_at)) if first_useful_at else None
    return SessionMetrics(
        version=POLICY_VERSION,
        session_count=len(sessions),
        displayed_count=displayed_count,
        useful_card_rate=useful_rate,
        already_known_reshow_rate=reshow_rate,
        cards_to_useful_item=cards_to_useful,
        feedback_response_rate=response_rate,
    )


def reset_session_telemetry(connection: sqlite3.Connection, *, user_id: str) -> int:
    """Delete this user's telemetry only. Ledger rows stay untouched."""
    before = ledger_world_state(connection)
    connection.execute("DELETE FROM feed_session_outcomes WHERE user_id = ?", (user_id,))
    deleted_sessions = connection.execute("DELETE FROM feed_sessions WHERE user_id = ?", (user_id,)).rowcount
    after = ledger_world_state(connection)
    if before != after:
        raise RuntimeError("session telemetry reset mutated the factual ledger")
    return int(deleted_sessions)


def prune_expired_telemetry(connection: sqlite3.Connection, *, now: int | None = None) -> int:
    cutoff = (int(time.time()) if now is None else now) - RETENTION_DAYS * 86_400
    expired = [
        str(row["id"])
        for row in connection.execute(
            "SELECT id FROM feed_sessions WHERE started_at < ?",
            (cutoff,),
        ).fetchall()
    ]
    if not expired:
        return 0
    placeholders = ",".join("?" for _ in expired)
    connection.execute(
        f"DELETE FROM feed_session_outcomes WHERE session_id IN ({placeholders})",  # nosec B608
        expired,
    )
    connection.execute(
        f"DELETE FROM feed_sessions WHERE id IN ({placeholders})",  # nosec B608
        expired,
    )
    return len(expired)


def _insert_outcome(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    session_id: str,
    kind: str,
    created_at: int,
    feed_item_id: str | None = None,
    feedback_type: str | None = None,
) -> SessionOutcome:
    oid = f"fso_{secrets.token_urlsafe(8)}"
    connection.execute(
        """
        INSERT INTO feed_session_outcomes (
            id, user_id, session_id, kind, feed_item_id, feedback_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (oid, user_id, session_id, kind, feed_item_id, feedback_type, created_at),
    )
    return SessionOutcome(
        id=oid,
        user_id=user_id,
        session_id=session_id,
        kind=kind,
        feed_item_id=feed_item_id,
        feedback_type=feedback_type,
        created_at=created_at,
    )


ACCOUNT_DELETION_TABLES = SESSION_TELEMETRY_TABLES
