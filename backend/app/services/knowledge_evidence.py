from __future__ import annotations

import secrets
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.db.knowledge_evidence_schema import KNOWLEDGE_EVIDENCE_TABLE

# MeStore.delete_account must delete this user-scoped table. Factual ledger
# tables (events, deltas, state_claims, observations, claim_relations, ...)
# are never modified by knowledge evidence.
ACCOUNT_DELETION_TABLE = KNOWLEDGE_EVIDENCE_TABLE

KIND_DELIVERED: Final = "delivered"
KIND_DISPLAYED: Final = "displayed"
KIND_READ: Final = "read"
KIND_ALREADY_KNEW: Final = "already_knew"
KIND_LEARNED_NOW: Final = "learned_now"
KIND_BASELINE: Final = "baseline"
KIND_BOOTSTRAP_EXPLICIT: Final = "bootstrap_explicit"
KIND_BOOTSTRAP_CHECKPOINT: Final = "bootstrap_checkpoint"
KIND_BOOTSTRAP_CLAIM: Final = "bootstrap_claim"
KIND_BOOTSTRAP_INFERRED: Final = "bootstrap_inferred"

EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        KIND_DELIVERED,
        KIND_DISPLAYED,
        KIND_READ,
        KIND_ALREADY_KNEW,
        KIND_LEARNED_NOW,
        KIND_BASELINE,
        KIND_BOOTSTRAP_EXPLICIT,
        KIND_BOOTSTRAP_CHECKPOINT,
        KIND_BOOTSTRAP_CLAIM,
        KIND_BOOTSTRAP_INFERRED,
    }
)
BOOTSTRAP_KINDS: Final[frozenset[str]] = frozenset(
    {
        KIND_BOOTSTRAP_EXPLICIT,
        KIND_BOOTSTRAP_CHECKPOINT,
        KIND_BOOTSTRAP_CLAIM,
        KIND_BOOTSTRAP_INFERRED,
    }
)

PROVENANCE_DELIVERY: Final = "delivery"
PROVENANCE_DISPLAY: Final = "display"
PROVENANCE_READ: Final = "read"
PROVENANCE_EXPLICIT_FEEDBACK: Final = "explicit_feedback"
PROVENANCE_BASELINE: Final = "baseline"
PROVENANCE_BOOTSTRAP: Final = "bootstrap"
PROVENANCE_BOOTSTRAP_CHECKPOINT: Final = "bootstrap_checkpoint"
PROVENANCE_BOOTSTRAP_INFERRED: Final = "bootstrap_inferred"

PROVENANCE_BY_KIND: Final[dict[str, str]] = {
    KIND_DELIVERED: PROVENANCE_DELIVERY,
    KIND_DISPLAYED: PROVENANCE_DISPLAY,
    KIND_READ: PROVENANCE_READ,
    KIND_ALREADY_KNEW: PROVENANCE_EXPLICIT_FEEDBACK,
    KIND_LEARNED_NOW: PROVENANCE_EXPLICIT_FEEDBACK,
    KIND_BASELINE: PROVENANCE_BASELINE,
    KIND_BOOTSTRAP_EXPLICIT: PROVENANCE_BOOTSTRAP,
    KIND_BOOTSTRAP_CHECKPOINT: PROVENANCE_BOOTSTRAP_CHECKPOINT,
    KIND_BOOTSTRAP_CLAIM: PROVENANCE_BOOTSTRAP,
    KIND_BOOTSTRAP_INFERRED: PROVENANCE_BOOTSTRAP_INFERRED,
}

CONFIDENCE_NONE: Final = "none"
CONFIDENCE_LOW: Final = "low"
CONFIDENCE_MEDIUM: Final = "medium"
CONFIDENCE_HIGH: Final = "high"

CONFIDENCE_BY_KIND: Final[dict[str, str]] = {
    KIND_DELIVERED: CONFIDENCE_LOW,
    KIND_DISPLAYED: CONFIDENCE_MEDIUM,
    KIND_READ: CONFIDENCE_MEDIUM,
    KIND_ALREADY_KNEW: CONFIDENCE_HIGH,
    KIND_LEARNED_NOW: CONFIDENCE_HIGH,
    KIND_BASELINE: CONFIDENCE_HIGH,
    KIND_BOOTSTRAP_EXPLICIT: CONFIDENCE_HIGH,
    KIND_BOOTSTRAP_CHECKPOINT: CONFIDENCE_HIGH,
    KIND_BOOTSTRAP_CLAIM: CONFIDENCE_HIGH,
    KIND_BOOTSTRAP_INFERRED: CONFIDENCE_LOW,
}

STATE_KNOWN: Final = "known"
STATE_PROBABLY_KNOWN: Final = "probably_known"
STATE_UNKNOWN: Final = "unknown"

KnowledgeState = Literal["known", "probably_known", "unknown"]
VisibilityAction = Literal["show", "demote", "hide"]
ConfidenceLevel = Literal["none", "low", "medium", "high"]

HIGH_VALUE_IMPORTANCE: Final[frozenset[str]] = frozenset({"high", "critical"})
EXPLICIT_KINDS: Final[frozenset[str]] = frozenset(
    {
        KIND_ALREADY_KNEW,
        KIND_LEARNED_NOW,
        KIND_BASELINE,
        KIND_BOOTSTRAP_EXPLICIT,
        KIND_BOOTSTRAP_CLAIM,
    }
)
IMPLICIT_VIEW_KINDS: Final[frozenset[str]] = frozenset({KIND_DISPLAYED, KIND_READ})


@dataclass(frozen=True)
class KnowledgeTarget:
    """Knowledge key. Claim IDs stay as stored; knowledge_id is the #50 target."""

    user_id: str
    claim_id: str | None = None
    event_id: str | None = None
    delta_id: str | None = None
    knowledge_id: str | None = None


@dataclass(frozen=True)
class KnowledgeEvidence:
    id: str
    user_id: str
    claim_id: str | None
    event_id: str | None
    delta_id: str | None
    kind: str
    provenance: str
    confidence: str
    source_id: str
    created_at: int


@dataclass(frozen=True)
class DerivedKnowledge:
    state: KnowledgeState
    confidence: ConfidenceLevel
    visibility: VisibilityAction
    evidence_count: int


class UnknownEvidenceKindError(ValueError):
    """Raised when an evidence kind is not part of the Known-01 model."""


def provenance_for_kind(kind: str) -> str:
    if kind not in PROVENANCE_BY_KIND:
        raise UnknownEvidenceKindError(kind)
    return PROVENANCE_BY_KIND[kind]


def confidence_for_kind(kind: str) -> str:
    if kind not in CONFIDENCE_BY_KIND:
        raise UnknownEvidenceKindError(kind)
    return CONFIDENCE_BY_KIND[kind]


def visibility_for_state(state: str, confidence: str) -> VisibilityAction:
    """Uncertain evidence may show or demote. It must never hide."""
    if state == STATE_KNOWN and confidence == CONFIDENCE_HIGH:
        return "hide"
    if state == STATE_PROBABLY_KNOWN:
        return "demote"
    return "show"


def may_hide(*, state: str, confidence: str, importance_level: str | None = None) -> bool:
    """Evidence-only hide check. The Known-05 composed guard is stricter.

    Uncertain evidence may show or demote. It must never hide. Callers that
    also have identity / revision / importance must use
    ``app.services.false_suppression.may_hide``.
    """
    del importance_level
    return state == STATE_KNOWN and confidence == CONFIDENCE_HIGH


def presentation_for_item(
    *,
    state: str,
    confidence: str,
    importance_level: str | None = None,
) -> VisibilityAction:
    action = visibility_for_state(state, confidence)
    if action == "hide" and not may_hide(
        state=state, confidence=confidence, importance_level=importance_level
    ):
        if importance_level in HIGH_VALUE_IMPORTANCE:
            return "show"
        return "demote"
    return action


def target_key(target: KnowledgeTarget) -> tuple[str, ...]:
    if target.knowledge_id:
        return ("knowledge", target.user_id, target.knowledge_id)
    if target.claim_id:
        return ("claim", target.user_id, target.claim_id)
    if target.event_id and target.delta_id:
        return ("delta", target.user_id, target.event_id, target.delta_id)
    if target.event_id:
        return ("event", target.user_id, target.event_id)
    return ("user", target.user_id)


def evidence_matches_target(row: KnowledgeEvidence, target: KnowledgeTarget) -> bool:
    if row.user_id != target.user_id:
        return False
    key = target_key(target)
    if key[0] == "knowledge":
        return False
    if key[0] == "claim":
        return row.claim_id == target.claim_id
    if key[0] == "delta":
        return row.event_id == target.event_id and row.delta_id == target.delta_id
    if key[0] == "event":
        return row.event_id == target.event_id
    return True


def derive_knowledge_state(evidence: Sequence[KnowledgeEvidence]) -> DerivedKnowledge:
    """Deterministic fold. Replay is this function over history ordered by time, id."""
    rows = sorted(evidence, key=lambda row: (row.created_at, row.id))
    state: KnowledgeState = STATE_UNKNOWN
    confidence: ConfidenceLevel = CONFIDENCE_NONE
    for row in rows:
        if row.kind == KIND_DELIVERED:
            if state == STATE_UNKNOWN and confidence == CONFIDENCE_NONE:
                confidence = CONFIDENCE_LOW
            continue
        if row.kind == KIND_BOOTSTRAP_CHECKPOINT:
            continue
        if row.kind == KIND_BOOTSTRAP_INFERRED:
            if state != STATE_KNOWN:
                state = STATE_PROBABLY_KNOWN
                if confidence != CONFIDENCE_HIGH:
                    confidence = CONFIDENCE_LOW
            continue
        if row.kind in IMPLICIT_VIEW_KINDS:
            if state != STATE_KNOWN:
                state = STATE_PROBABLY_KNOWN
                confidence = CONFIDENCE_MEDIUM
            continue
        if row.kind in EXPLICIT_KINDS:
            state = STATE_KNOWN
            confidence = CONFIDENCE_HIGH
    return DerivedKnowledge(
        state=state,
        confidence=confidence,
        visibility=visibility_for_state(state, confidence),
        evidence_count=len(rows),
    )


def append_knowledge_evidence(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    kind: str,
    source_id: str,
    claim_id: str | None = None,
    event_id: str | None = None,
    delta_id: str | None = None,
    created_at: int | None = None,
    evidence_id: str | None = None,
) -> bool:
    """Append one audit row. Same (user, kind, source_id) is idempotent."""
    if kind not in EVIDENCE_KINDS:
        raise UnknownEvidenceKindError(kind)
    if not source_id:
        raise ValueError("source_id is required for idempotent knowledge evidence")
    inserted = connection.execute(
        """
        INSERT OR IGNORE INTO user_knowledge_evidence (
            id, user_id, claim_id, event_id, delta_id,
            kind, provenance, confidence, source_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id or f"knev_{secrets.token_urlsafe(8)}",
            user_id,
            claim_id,
            event_id,
            delta_id,
            kind,
            provenance_for_kind(kind),
            confidence_for_kind(kind),
            source_id,
            int(time.time()) if created_at is None else created_at,
        ),
    ).rowcount
    return inserted == 1


def list_knowledge_evidence(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str | None = None,
    event_id: str | None = None,
    delta_id: str | None = None,
    knowledge_id: str | None = None,
) -> list[KnowledgeEvidence]:
    target = KnowledgeTarget(
        user_id=user_id,
        claim_id=claim_id,
        event_id=event_id,
        delta_id=delta_id,
        knowledge_id=knowledge_id,
    )
    rows = connection.execute(
        """
        SELECT id, user_id, claim_id, event_id, delta_id,
               kind, provenance, confidence, source_id, created_at
        FROM user_knowledge_evidence
        WHERE user_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (user_id,),
    ).fetchall()
    evidence = [_row_to_evidence(row) for row in rows]
    if target.knowledge_id:
        from app.services.knowledge_identity import claims_for_knowledge_id

        allowed = set(claims_for_knowledge_id(connection, target.knowledge_id))
        return [row for row in evidence if row.claim_id in allowed]
    if target_key(target)[0] == "user":
        return evidence
    return [row for row in evidence if evidence_matches_target(row, target)]


def replay_knowledge_state(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    claim_id: str | None = None,
    event_id: str | None = None,
    delta_id: str | None = None,
    knowledge_id: str | None = None,
) -> DerivedKnowledge:
    return derive_knowledge_state(
        list_knowledge_evidence(
            connection,
            user_id=user_id,
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            knowledge_id=knowledge_id,
        )
    )


def _row_to_evidence(row: sqlite3.Row) -> KnowledgeEvidence:
    return KnowledgeEvidence(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        claim_id=row["claim_id"],
        event_id=row["event_id"],
        delta_id=row["delta_id"],
        kind=str(row["kind"]),
        provenance=str(row["provenance"]),
        confidence=str(row["confidence"]),
        source_id=str(row["source_id"]),
        created_at=int(row["created_at"]),
    )
