"""Follow-time knowledge baseline (Known-04).

When a user starts following a topic/event/source, record KIND_BASELINE
evidence for claims already true at that moment. Replay of that evidence
makes those claims known for ranking so years of history do not flood the
feed as unknown. Deltas that become true after follow time stay unknown.

Unfollow/delete-topic/remove-source must not rewrite the factual ledger and
must not delete this evidence. Catch-up is explicit: it persists the follow
timestamp but does not mark historical claims known.

No schema migration: reuses user_knowledge_evidence KIND_BASELINE from #49.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

from app.services.knowledge_evidence import (
    KIND_ALREADY_KNEW,
    KIND_BASELINE,
    KIND_LEARNED_NOW,
    PROVENANCE_BASELINE,
    STATE_KNOWN,
    STATE_PROBABLY_KNOWN,
    STATE_UNKNOWN,
    append_knowledge_evidence,
    list_knowledge_evidence,
    replay_knowledge_state,
)
from app.services.relation import _normalize

SUBJECT_EVENT: Final = "event"
SUBJECT_TOPIC: Final = "topic"
SUBJECT_SOURCE: Final = "source"

FollowSubject = Literal["event", "topic", "source"]

_EXPLICIT_KNOWN_KINDS: Final[frozenset[str]] = frozenset(
    {KIND_BASELINE, KIND_ALREADY_KNEW, KIND_LEARNED_NOW}
)


@dataclass(frozen=True)
class FollowBaseline:
    user_id: str
    subject_kind: str
    subject_id: str
    followed_at: int
    catch_up: bool
    checkpoint_source_id: str
    claim_ids: tuple[str, ...]


def follow_iso(followed_at: int) -> str:
    return datetime.fromtimestamp(followed_at, UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def checkpoint_source_id(subject_kind: str, subject_id: str) -> str:
    return f"follow:{subject_kind}:{subject_id}"


def start_source_id(
    subject_kind: str,
    subject_id: str,
    followed_at: int,
    *,
    catch_up: bool = False,
) -> str:
    marker = "catchup" if catch_up else "start"
    return f"follow:{subject_kind}:{subject_id}:{marker}:{followed_at}"


def claim_baseline_source_id(subject_kind: str, subject_id: str, claim_id: str) -> str:
    return f"follow:{subject_kind}:{subject_id}:claim:{claim_id}"


def event_ids_matching_topic(connection: sqlite3.Connection, topic_name: str) -> tuple[str, ...]:
    token = _normalize(topic_name)
    if not token:
        return ()
    ids: list[str] = []
    events = connection.execute(
        """
        SELECT e.id, e.title, e.summary, COALESCE(le.source_key, '') AS source_key
        FROM events e
        LEFT JOIN ledger_events le ON le.id = e.id
        """
    ).fetchall()
    for event in events:
        padded = f" {_normalize(' '.join((event['source_key'], event['title'], event['summary'])))} "
        if f" {token} " in padded:
            ids.append(str(event["id"]))
    return tuple(ids)


def event_ids_for_source(
    connection: sqlite3.Connection,
    *,
    source_type: str,
    source_key: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT id FROM ledger_events
        WHERE source_type = ? AND source_key = ?
        ORDER BY id
        """,
        (source_type, source_key),
    ).fetchall()
    return tuple(str(row["id"]) for row in rows)


def claims_already_true_at(
    connection: sqlite3.Connection,
    *,
    event_ids: Sequence[str],
    as_of_iso: str,
) -> tuple[sqlite3.Row, ...]:
    ids = tuple(dict.fromkeys(event_id for event_id in event_ids if event_id))
    if not ids:
        return ()
    placeholders = ",".join("?" for _ in ids)
    return tuple(
        connection.execute(
            f"""
            SELECT c.id AS claim_id, c.event_id, m.delta_id, c.valid_at
            FROM state_claims c
            LEFT JOIN delta_claim_map m ON m.claim_id = c.id
            WHERE c.event_id IN ({placeholders})
              AND c.valid_at <= ?
            ORDER BY c.valid_at ASC, c.id ASC
            """,  # nosec B608
            (*ids, as_of_iso),
        ).fetchall()
    )


def resolve_follow_event_ids(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_id: str,
    topic_name: str | None = None,
    source_type: str | None = None,
    source_key: str | None = None,
) -> tuple[str, ...]:
    if subject_kind == SUBJECT_EVENT:
        return (subject_id,)
    if subject_kind == SUBJECT_TOPIC:
        return event_ids_matching_topic(connection, topic_name or subject_id)
    if subject_kind == SUBJECT_SOURCE:
        if not source_type or not source_key:
            parts = subject_id.split(":", 1)
            if len(parts) != 2:
                return ()
            source_type, source_key = parts
        return event_ids_for_source(
            connection,
            source_type=source_type,
            source_key=source_key,
        )
    return ()


def record_follow_baseline(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    subject_kind: str,
    subject_id: str,
    catch_up: bool = False,
    followed_at: int | None = None,
    event_ids: Sequence[str] | None = None,
    topic_name: str | None = None,
    source_type: str | None = None,
    source_key: str | None = None,
) -> FollowBaseline:
    """Persist a start-from-now baseline. catch_up records the timestamp only."""
    if subject_kind not in {SUBJECT_EVENT, SUBJECT_TOPIC, SUBJECT_SOURCE}:
        raise ValueError(f"unsupported follow subject: {subject_kind}")
    at = int(time.time()) if followed_at is None else followed_at
    as_of = follow_iso(at)
    checkpoint = checkpoint_source_id(subject_kind, subject_id)
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_BASELINE,
        source_id=checkpoint,
        created_at=at,
    )
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_BASELINE,
        source_id=start_source_id(subject_kind, subject_id, at, catch_up=catch_up),
        created_at=at,
    )
    if catch_up:
        return FollowBaseline(
            user_id=user_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            followed_at=at,
            catch_up=True,
            checkpoint_source_id=checkpoint,
            claim_ids=(),
        )

    resolved = (
        tuple(event_ids)
        if event_ids is not None
        else resolve_follow_event_ids(
            connection,
            subject_kind=subject_kind,
            subject_id=subject_id,
            topic_name=topic_name,
            source_type=source_type,
            source_key=source_key,
        )
    )
    claim_ids: list[str] = []
    for row in claims_already_true_at(connection, event_ids=resolved, as_of_iso=as_of):
        claim_id = str(row["claim_id"])
        append_knowledge_evidence(
            connection,
            user_id=user_id,
            kind=KIND_BASELINE,
            source_id=claim_baseline_source_id(subject_kind, subject_id, claim_id),
            claim_id=claim_id,
            event_id=str(row["event_id"]),
            delta_id=row["delta_id"],
            created_at=at,
        )
        claim_ids.append(claim_id)
    return FollowBaseline(
        user_id=user_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        followed_at=at,
        catch_up=False,
        checkpoint_source_id=checkpoint,
        claim_ids=tuple(dict.fromkeys(claim_ids)),
    )


def list_follow_checkpoints(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    subject_kind: str | None = None,
    subject_id: str | None = None,
) -> tuple[FollowBaseline, ...]:
    """Replay follow-start timestamps from append-only baseline evidence."""
    rows = list_knowledge_evidence(connection, user_id=user_id)
    starts = [
        row
        for row in rows
        if row.kind == KIND_BASELINE
        and row.source_id.startswith("follow:")
        and (":start:" in row.source_id or ":catchup:" in row.source_id)
    ]
    results: list[FollowBaseline] = []
    for row in starts:
        parts = row.source_id.split(":")
        # follow:{kind}:{id}:start|{catchup}:{ts} — id may contain colons for sources
        if len(parts) < 5 or parts[0] != "follow" or parts[-2] not in {"start", "catchup"}:
            continue
        kind = parts[1]
        followed_at = int(parts[-1])
        sid = ":".join(parts[2:-2])
        catch_up = parts[-2] == "catchup"
        if subject_kind is not None and kind != subject_kind:
            continue
        if subject_id is not None and sid != subject_id:
            continue
        claim_ids = tuple(
            evidence.claim_id
            for evidence in rows
            if evidence.kind == KIND_BASELINE
            and evidence.claim_id
            and evidence.source_id.startswith(f"follow:{kind}:{sid}:claim:")
        )
        results.append(
            FollowBaseline(
                user_id=user_id,
                subject_kind=kind,
                subject_id=sid,
                followed_at=followed_at,
                catch_up=catch_up,
                checkpoint_source_id=checkpoint_source_id(kind, sid),
                claim_ids=() if catch_up else claim_ids,
            )
        )
    return tuple(sorted(results, key=lambda item: (item.followed_at, item.subject_kind, item.subject_id)))


def ranking_knownness(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str | None,
) -> str:
    """Knownness used for feed ranking. Uncertain is never treated as hide."""
    if not claim_id:
        return STATE_UNKNOWN
    derived = replay_knowledge_state(connection, user_id=user_id, claim_id=claim_id)
    return derived.state


def ranking_knownness_score(state: str) -> int:
    """Higher score surfaces first. Unknown outranks probably_known and known."""
    if state == STATE_UNKNOWN:
        return 2
    if state == STATE_PROBABLY_KNOWN:
        return 1
    return 0


def is_explicit_known_kind(kind: str) -> bool:
    return kind in _EXPLICIT_KNOWN_KINDS


def baseline_provenance() -> str:
    return PROVENANCE_BASELINE
