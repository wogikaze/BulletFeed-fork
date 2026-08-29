"""Pre-existing user knowledge bootstrap (Known-08).

Users already know facts from outside BulletFeed. This module records that
knowledge as bootstrap evidence so ranking can demote restatements, without
pretending the user learned the fact from a BulletFeed delivery.

No schema migration: reuses user_knowledge_evidence with distinct kinds.
No third-party history is imported. Inferred bootstrap cannot hide.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.services.false_suppression import decide_suppression
from app.services.follow_baseline import (
    SUBJECT_EVENT,
    SUBJECT_TOPIC,
    claims_already_true_at,
    follow_iso,
    resolve_follow_event_ids,
)
from app.services.knowledge_evidence import (
    BOOTSTRAP_KINDS,
    CONFIDENCE_HIGH,
    KIND_BOOTSTRAP_CHECKPOINT,
    KIND_BOOTSTRAP_CLAIM,
    KIND_BOOTSTRAP_EXPLICIT,
    KIND_BOOTSTRAP_INFERRED,
    STATE_KNOWN,
    STATE_PROBABLY_KNOWN,
    STATE_UNKNOWN,
    KnowledgeEvidence,
    append_knowledge_evidence,
    derive_knowledge_state,
    list_knowledge_evidence,
    replay_knowledge_state,
)

POLICY_VERSION: Final = "knowledge-bootstrap-v1"

SUBJECT_GLOBAL: Final = "global"
BootstrapSubject = Literal["event", "topic", "global"]
BOOTSTRAP_SUBJECTS: Final[frozenset[str]] = frozenset({SUBJECT_EVENT, SUBJECT_TOPIC, SUBJECT_GLOBAL})


@dataclass(frozen=True)
class BootstrapCheckpoint:
    user_id: str
    subject_kind: str
    subject_id: str
    as_of: int
    catch_up: bool
    source_id: str
    claim_ids: tuple[str, ...]


@dataclass(frozen=True)
class BootstrapSummary:
    explicit_claim_ids: tuple[str, ...]
    inferred_claim_ids: tuple[str, ...]
    checkpoints: tuple[BootstrapCheckpoint, ...]
    evidence: tuple[KnowledgeEvidence, ...]


@dataclass(frozen=True)
class BootstrapEvalCase:
    case_id: str
    evidence: tuple[KnowledgeEvidence, ...]
    gold_known: bool
    importance_level: str = "high"


@dataclass(frozen=True)
class BootstrapEvalReport:
    precision: float
    unknown_but_hidden: int
    inferred_hide_count: int
    case_count: int


class UnknownBootstrapClaimError(ValueError):
    """Raised when a requested claim is not in the factual ledger."""


class UnknownBootstrapSubjectError(ValueError):
    """Raised when a checkpoint subject kind is not supported."""


def session_source_id(session_id: str) -> str:
    return f"bootstrap:session:{session_id}"


def explicit_source_id(session_id: str, claim_id: str) -> str:
    return f"bootstrap:explicit:{session_id}:{claim_id}"


def checkpoint_source_id(subject_kind: str, subject_id: str) -> str:
    return f"bootstrap:checkpoint:{subject_kind}:{subject_id}"


def checkpoint_start_source_id(
    subject_kind: str,
    subject_id: str,
    as_of: int,
    *,
    catch_up: bool = False,
) -> str:
    marker = "catchup" if catch_up else "start"
    return f"bootstrap:checkpoint:{subject_kind}:{subject_id}:{marker}:{as_of}"


def checkpoint_claim_source_id(subject_kind: str, subject_id: str, claim_id: str) -> str:
    return f"bootstrap:checkpoint:{subject_kind}:{subject_id}:claim:{claim_id}"


def inferred_source_id(claim_id: str) -> str:
    return f"bootstrap:inferred:{claim_id}"


def is_bootstrap_evidence(row: KnowledgeEvidence) -> bool:
    return row.kind in BOOTSTRAP_KINDS


def new_session_id() -> str:
    return f"kbs_{secrets.token_urlsafe(8)}"


def _require_claim(connection: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT c.id AS claim_id, c.event_id, m.delta_id
        FROM state_claims c
        LEFT JOIN delta_claim_map m ON m.claim_id = c.id
        WHERE c.id = ?
        """,
        (claim_id,),
    ).fetchone()
    if row is None:
        raise UnknownBootstrapClaimError(claim_id)
    return row


def record_explicit_bootstrap(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_ids: Sequence[str],
    session_id: str | None = None,
    created_at: int | None = None,
) -> tuple[str, tuple[str, ...]]:
    """User-confirmed pre-existing knowledge. Not a BulletFeed delivery."""
    sid = session_id or new_session_id()
    at = int(time.time()) if created_at is None else created_at
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_BOOTSTRAP_CHECKPOINT,
        source_id=session_source_id(sid),
        created_at=at,
    )
    recorded: list[str] = []
    for claim_id in dict.fromkeys(claim_id for claim_id in claim_ids if claim_id):
        row = _require_claim(connection, claim_id)
        append_knowledge_evidence(
            connection,
            user_id=user_id,
            kind=KIND_BOOTSTRAP_EXPLICIT,
            source_id=explicit_source_id(sid, claim_id),
            claim_id=claim_id,
            event_id=str(row["event_id"]),
            delta_id=row["delta_id"],
            created_at=at,
        )
        recorded.append(claim_id)
    return sid, tuple(recorded)


def record_current_state_checkpoint(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    subject_kind: str,
    subject_id: str,
    catch_up: bool = False,
    as_of: int | None = None,
    topic_name: str | None = None,
    event_ids: Sequence[str] | None = None,
) -> BootstrapCheckpoint:
    """Mark claims already true at as_of. Intermediate history after as_of stays unknown.

    catch_up records the checkpoint timestamp only. It does not claim the user
    knows historical intermediate states.
    """
    if subject_kind not in BOOTSTRAP_SUBJECTS:
        raise UnknownBootstrapSubjectError(subject_kind)
    at = int(time.time()) if as_of is None else as_of
    as_of_iso = follow_iso(at)
    checkpoint = checkpoint_source_id(subject_kind, subject_id)
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_BOOTSTRAP_CHECKPOINT,
        source_id=checkpoint,
        created_at=at,
    )
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_BOOTSTRAP_CHECKPOINT,
        source_id=checkpoint_start_source_id(subject_kind, subject_id, at, catch_up=catch_up),
        created_at=at,
    )
    if catch_up or subject_kind == SUBJECT_GLOBAL:
        return BootstrapCheckpoint(
            user_id=user_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            as_of=at,
            catch_up=True if subject_kind == SUBJECT_GLOBAL else catch_up,
            source_id=checkpoint,
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
        )
    )
    claim_ids: list[str] = []
    for row in claims_already_true_at(connection, event_ids=resolved, as_of_iso=as_of_iso):
        claim_id = str(row["claim_id"])
        append_knowledge_evidence(
            connection,
            user_id=user_id,
            kind=KIND_BOOTSTRAP_CLAIM,
            source_id=checkpoint_claim_source_id(subject_kind, subject_id, claim_id),
            claim_id=claim_id,
            event_id=str(row["event_id"]),
            delta_id=row["delta_id"],
            created_at=at,
        )
        claim_ids.append(claim_id)
    return BootstrapCheckpoint(
        user_id=user_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        as_of=at,
        catch_up=False,
        source_id=checkpoint,
        claim_ids=tuple(dict.fromkeys(claim_ids)),
    )


def record_inferred_bootstrap(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str,
    created_at: int | None = None,
) -> None:
    """Low-confidence inferred seed. Tests and explicit tools only. Cannot hide."""
    row = _require_claim(connection, claim_id)
    append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=KIND_BOOTSTRAP_INFERRED,
        source_id=inferred_source_id(claim_id),
        claim_id=claim_id,
        event_id=str(row["event_id"]),
        delta_id=row["delta_id"],
        created_at=created_at,
    )


def list_bootstrap_evidence(connection: sqlite3.Connection, *, user_id: str) -> tuple[KnowledgeEvidence, ...]:
    return tuple(
        row for row in list_knowledge_evidence(connection, user_id=user_id) if is_bootstrap_evidence(row)
    )


def list_bootstrap_checkpoints(
    connection: sqlite3.Connection, *, user_id: str
) -> tuple[BootstrapCheckpoint, ...]:
    rows = list_bootstrap_evidence(connection, user_id=user_id)
    starts = [
        row
        for row in rows
        if row.kind == KIND_BOOTSTRAP_CHECKPOINT
        and row.source_id.startswith("bootstrap:checkpoint:")
        and (":start:" in row.source_id or ":catchup:" in row.source_id)
    ]
    results: list[BootstrapCheckpoint] = []
    for row in starts:
        parts = row.source_id.split(":")
        if len(parts) < 5 or parts[-2] not in {"start", "catchup"}:
            continue
        subject_kind = parts[2]
        as_of = int(parts[-1])
        subject_id = ":".join(parts[3:-2])
        catch_up = parts[-2] == "catchup"
        claim_ids = tuple(
            evidence.claim_id
            for evidence in rows
            if evidence.kind == KIND_BOOTSTRAP_CLAIM
            and evidence.claim_id
            and evidence.source_id.startswith(f"bootstrap:checkpoint:{subject_kind}:{subject_id}:claim:")
        )
        results.append(
            BootstrapCheckpoint(
                user_id=user_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                as_of=as_of,
                catch_up=catch_up,
                source_id=checkpoint_source_id(subject_kind, subject_id),
                claim_ids=() if catch_up else claim_ids,
            )
        )
    return tuple(sorted(results, key=lambda item: (item.as_of, item.subject_kind, item.subject_id)))


def inspect_bootstrap(connection: sqlite3.Connection, *, user_id: str) -> BootstrapSummary:
    evidence = list_bootstrap_evidence(connection, user_id=user_id)
    explicit = tuple(row.claim_id for row in evidence if row.kind == KIND_BOOTSTRAP_EXPLICIT and row.claim_id)
    inferred = tuple(row.claim_id for row in evidence if row.kind == KIND_BOOTSTRAP_INFERRED and row.claim_id)
    return BootstrapSummary(
        explicit_claim_ids=tuple(dict.fromkeys(explicit)),
        inferred_claim_ids=tuple(dict.fromkeys(inferred)),
        checkpoints=list_bootstrap_checkpoints(connection, user_id=user_id),
        evidence=evidence,
    )


def reset_bootstrap_knowledge(connection: sqlite3.Connection, *, user_id: str) -> int:
    """Delete bootstrap evidence only. Delivery / feedback / baseline stay.

    Does not touch Event / Claim / Delta / Observation rows.
    """
    kinds = tuple(sorted(BOOTSTRAP_KINDS))
    placeholders = ",".join("?" for _ in kinds)
    deleted = connection.execute(
        f"""
        DELETE FROM user_knowledge_evidence
        WHERE user_id = ? AND kind IN ({placeholders})
        """,  # nosec B608
        (user_id, *kinds),
    ).rowcount
    return int(deleted)


def ranking_knownness(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str | None,
) -> str:
    if not claim_id:
        return STATE_UNKNOWN
    return replay_knowledge_state(connection, user_id=user_id, claim_id=claim_id).state


def evaluate_bootstrap_impact(cases: Sequence[BootstrapEvalCase]) -> BootstrapEvalReport:
    """#55-compatible bootstrap precision and false-suppression impact.

    Blind labels are not consulted. Production fold + #53 guard are used as-is.
    """
    if not cases:
        return BootstrapEvalReport(precision=0.0, unknown_but_hidden=0, inferred_hide_count=0, case_count=0)
    predicted_known = 0
    gold_known = 0
    true_known = 0
    unknown_but_hidden = 0
    inferred_hide_count = 0
    for case in cases:
        derived = derive_knowledge_state(case.evidence)
        predicted = derived.state == STATE_KNOWN
        if case.gold_known:
            gold_known += 1
            if predicted:
                true_known += 1
        if predicted:
            predicted_known += 1
        decision = decide_suppression(
            knowledge_state=derived.state,
            knowledge_confidence=derived.confidence,
            importance_level=case.importance_level,
        )
        if not case.gold_known and decision.action == "hide":
            unknown_but_hidden += 1
        if any(row.kind == KIND_BOOTSTRAP_INFERRED for row in case.evidence):
            if derived.state == STATE_KNOWN and derived.confidence == CONFIDENCE_HIGH:
                inferred_hide_count += 1
            if decision.action == "hide":
                inferred_hide_count += 1
        if derived.state == STATE_PROBABLY_KNOWN and decision.action == "hide":
            inferred_hide_count += 1
    precision = (true_known / predicted_known) if predicted_known else 1.0
    return BootstrapEvalReport(
        precision=precision,
        unknown_but_hidden=unknown_but_hidden,
        inferred_hide_count=inferred_hide_count,
        case_count=len(cases),
    )
