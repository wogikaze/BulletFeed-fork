from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.db.knowledge_identity_schema import (
    CLAIM_KNOWLEDGE_MAP_TABLE,
    KNOWLEDGE_IDENTITY_TABLE,
)
from app.services.claim_semantics import (
    DEFAULT_EQUIVALENCE_POLICY,
    CanonicalClaim,
    SemanticEquivalencePolicy,
    canonicalize_claim,
    compare_claims,
)
from app.services.knowledge_evidence import (
    DerivedKnowledge,
    KnowledgeEvidence,
    VisibilityAction,
    derive_knowledge_state,
    list_knowledge_evidence,
)

# Derived mapping tables only. Factual ledger tables are never written here.
KNOWLEDGE_IDENTITY_TABLES: tuple[str, str] = (
    CLAIM_KNOWLEDGE_MAP_TABLE,
    KNOWLEDGE_IDENTITY_TABLE,
)

KNOWLEDGE_IDENTITY_VERSION = "knowledge-identity-v1"

IdentityLabel = Literal["same_target", "different_target", "uncertain"]
Confidence = Literal["high", "medium", "low"]

_DATE_TOKEN_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CVE_RE = re.compile(r"\bcve-\d{4}-\d{4,}\b", re.IGNORECASE)
_GHSA_RE = re.compile(r"\bghsa-[a-z0-9]+(?:-[a-z0-9]+)+\b", re.IGNORECASE)
_SOURCE_FRAME_PREFIXES = (
    "we are ",
    "we're ",
    "we were ",
    "our team is ",
    "the team is ",
    "we ",
)


@dataclass(frozen=True)
class KnowledgeIdentityFingerprint:
    identity_id: str
    slot: str
    value_tokens: tuple[str, ...]
    detail_tokens: tuple[str, ...]
    numbers: tuple[str, ...]
    versions: tuple[str, ...]
    dates: tuple[str, ...]
    stable_ids: tuple[str, ...]
    negated: bool
    version: str
    payload_json: str


@dataclass(frozen=True)
class KnowledgeIdentityDecision:
    label: IdentityLabel
    reason: str
    confidence: Confidence
    version: str
    left_identity_id: str
    right_identity_id: str
    shared_identity_id: str | None


@dataclass(frozen=True)
class KnowledgeIdentityMapping:
    claim_id: str
    knowledge_id: str
    reason: str
    confidence: str
    version: str
    decision: str


@dataclass(frozen=True)
class _ClaimRecord:
    claim_id: str
    slot: str
    value: str
    detail: str


def fingerprint_claim(
    *,
    value: str,
    detail: str = "",
    slot: str = "",
) -> KnowledgeIdentityFingerprint:
    canonical = canonicalize_claim(
        _prepare_identity_text(value),
        _prepare_identity_text(detail),
    )
    return _fingerprint_canonical(canonical, slot=slot)


def compare_knowledge_identity(
    left_value: str,
    left_detail: str,
    right_value: str,
    right_detail: str,
    *,
    left_slot: str = "",
    right_slot: str = "",
    policy: SemanticEquivalencePolicy = DEFAULT_EQUIVALENCE_POLICY,
) -> KnowledgeIdentityDecision:
    """Decide whether two claims are one knowledge target.

    Hard guards (numeric / version / date / negation / stable IDs) refuse a
    merge. Ambiguous overlap abstains so a false split is preferred to a false merge.
    """
    left = fingerprint_claim(value=left_value, detail=left_detail, slot=left_slot)
    right = fingerprint_claim(value=right_value, detail=right_detail, slot=right_slot)
    version = KNOWLEDGE_IDENTITY_VERSION
    if left.identity_id == right.identity_id:
        return KnowledgeIdentityDecision(
            "same_target",
            "canonical fingerprint is identical",
            "high",
            version,
            left.identity_id,
            right.identity_id,
            left.identity_id,
        )
    guard = _hard_guard(left, right)
    if guard is not None:
        label, reason, confidence = guard
        return KnowledgeIdentityDecision(
            label,
            reason,
            confidence,
            version,
            left.identity_id,
            right.identity_id,
            None,
        )
    equivalence = compare_claims(
        _prepare_identity_text(left_value),
        _prepare_identity_text(left_detail),
        _prepare_identity_text(right_value),
        _prepare_identity_text(right_detail),
        policy=policy,
    )
    if equivalence.label == "equivalent":
        shared = min(left.identity_id, right.identity_id)
        return KnowledgeIdentityDecision(
            "same_target",
            f"equivalent restatement: {equivalence.reason}",
            equivalence.confidence,
            version,
            left.identity_id,
            right.identity_id,
            shared,
        )
    if equivalence.label == "uncertain":
        return KnowledgeIdentityDecision(
            "uncertain",
            f"ambiguous match abstains: {equivalence.reason}",
            "low",
            version,
            left.identity_id,
            right.identity_id,
            None,
        )
    return KnowledgeIdentityDecision(
        "different_target",
        f"claims are not the same fact: {equivalence.reason}",
        equivalence.confidence,
        version,
        left.identity_id,
        right.identity_id,
        None,
    )


def identity_may_hide(decision: KnowledgeIdentityDecision) -> bool:
    """Uncertain identity never causes hide. Only a confident same-target may."""
    return decision.label == "same_target" and decision.confidence == "high"


def visibility_for_identity(
    decision: KnowledgeIdentityDecision,
    derived: DerivedKnowledge,
) -> VisibilityAction:
    if not identity_may_hide(decision) and derived.visibility == "hide":
        if decision.label == "same_target":
            return "demote"
        return "show"
    if decision.label != "same_target":
        return "show"
    return derived.visibility


def persist_knowledge_identity(
    connection: sqlite3.Connection,
    fingerprint: KnowledgeIdentityFingerprint,
    *,
    created_at: int | None = None,
) -> str:
    connection.execute(
        """
        INSERT OR IGNORE INTO knowledge_identities (
            id, fingerprint_json, version, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            fingerprint.identity_id,
            fingerprint.payload_json,
            fingerprint.version,
            int(time.time()) if created_at is None else created_at,
        ),
    )
    return fingerprint.identity_id


def map_claim_to_knowledge(
    connection: sqlite3.Connection,
    *,
    claim_id: str,
    knowledge_id: str,
    reason: str,
    confidence: str,
    decision: str,
    created_at: int | None = None,
) -> KnowledgeIdentityMapping:
    stamp = int(time.time()) if created_at is None else created_at
    connection.execute(
        """
        INSERT INTO claim_knowledge_map (
            claim_id, knowledge_id, reason, confidence, version, decision, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(claim_id) DO UPDATE SET
            knowledge_id = excluded.knowledge_id,
            reason = excluded.reason,
            confidence = excluded.confidence,
            version = excluded.version,
            decision = excluded.decision,
            created_at = excluded.created_at
        """,
        (
            claim_id,
            knowledge_id,
            reason,
            confidence,
            KNOWLEDGE_IDENTITY_VERSION,
            decision,
            stamp,
        ),
    )
    return KnowledgeIdentityMapping(
        claim_id=claim_id,
        knowledge_id=knowledge_id,
        reason=reason,
        confidence=confidence,
        version=KNOWLEDGE_IDENTITY_VERSION,
        decision=decision,
    )


def ensure_claim_knowledge_mapping(
    connection: sqlite3.Connection,
    *,
    claim_id: str,
    value: str,
    detail: str = "",
    slot: str = "",
    created_at: int | None = None,
) -> KnowledgeIdentityMapping:
    """Attach a claim to its fingerprint identity without rewriting the Claim ID."""
    existing = resolve_claim_knowledge_id(connection, claim_id)
    if existing is not None:
        return existing
    fingerprint = fingerprint_claim(value=value, detail=detail, slot=slot)
    persist_knowledge_identity(connection, fingerprint, created_at=created_at)
    return map_claim_to_knowledge(
        connection,
        claim_id=claim_id,
        knowledge_id=fingerprint.identity_id,
        reason="no equivalent peer; claim-scoped identity",
        confidence="high",
        decision="singleton",
        created_at=created_at,
    )


def _mapping_from_row(row: sqlite3.Row) -> KnowledgeIdentityMapping:
    return KnowledgeIdentityMapping(
        claim_id=str(row["claim_id"]),
        knowledge_id=str(row["knowledge_id"]),
        reason=str(row["reason"]),
        confidence=str(row["confidence"]),
        version=str(row["version"]),
        decision=str(row["decision"]),
    )


def resolve_claim_knowledge_id(
    connection: sqlite3.Connection,
    claim_id: str,
) -> KnowledgeIdentityMapping | None:
    mapped = resolve_claim_knowledge_ids(connection, (claim_id,))
    return mapped.get(claim_id)


def resolve_claim_knowledge_ids(
    connection: sqlite3.Connection,
    claim_ids: Sequence[str],
) -> dict[str, KnowledgeIdentityMapping]:
    unique = tuple(dict.fromkeys(claim_id for claim_id in claim_ids if claim_id))
    if not unique:
        return {}
    placeholders = ",".join("?" for _ in unique)
    rows = connection.execute(
        f"""
        SELECT claim_id, knowledge_id, reason, confidence, version, decision
        FROM claim_knowledge_map
        WHERE claim_id IN ({placeholders})
        """,  # noqa: S608  # nosec B608
        unique,
    ).fetchall()
    return {str(row["claim_id"]): _mapping_from_row(row) for row in rows}


def claims_for_knowledge_id(
    connection: sqlite3.Connection,
    knowledge_id: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT claim_id
        FROM claim_knowledge_map
        WHERE knowledge_id = ?
        ORDER BY claim_id
        """,
        (knowledge_id,),
    ).fetchall()
    return tuple(str(row["claim_id"]) for row in rows)


def list_knowledge_evidence_for_identity(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    knowledge_id: str,
) -> list[KnowledgeEvidence]:
    """Evidence stays keyed by Claim ID; identity only groups the lookup."""
    claim_ids = set(claims_for_knowledge_id(connection, knowledge_id))
    if not claim_ids:
        return []
    return [
        row
        for row in list_knowledge_evidence(connection, user_id=user_id)
        if row.claim_id in claim_ids
    ]


def replay_knowledge_state_for_identity(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    knowledge_id: str,
) -> DerivedKnowledge:
    return derive_knowledge_state(
        list_knowledge_evidence_for_identity(
            connection, user_id=user_id, knowledge_id=knowledge_id
        )
    )



def attach_knowledge_identity_for_claim(
    connection: sqlite3.Connection,
    *,
    claim_id: str,
    created_at: int | None = None,
) -> tuple[KnowledgeIdentityMapping, ...]:
    """Map one new claim without a full pairwise rebuild.

    Prior same-slot merges are preserved via existing claim_knowledge_map rows.
    Only the new claim is compared to peers (O(n) vs O(n^2) per ingest).
    Uncertain comparisons stay split. Full rebuild remains for backfill.
    """
    target_rows = _load_claim_records(connection, (claim_id,))
    if not target_rows:
        return ()
    target = target_rows[0]
    peers = [row for row in _load_claim_records(connection, None) if row.slot == target.slot]
    if len(peers) == 1:
        return rebuild_knowledge_identities(
            connection, claim_ids=(claim_id,), created_at=created_at
        )

    stamp = int(time.time()) if created_at is None else created_at
    parent = {row.claim_id: row.claim_id for row in peers}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left_id: str, right_id: str) -> None:
        left_root, right_root = find(left_id), find(right_id)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    existing = resolve_claim_knowledge_ids(connection, tuple(row.claim_id for row in peers))
    by_knowledge: dict[str, list[str]] = {}
    for mapped_id, mapping in existing.items():
        by_knowledge.setdefault(mapping.knowledge_id, []).append(mapped_id)
    for group in by_knowledge.values():
        anchor = group[0]
        for other in group[1:]:
            union(anchor, other)

    reasons: dict[str, tuple[str, str, str]] = {}
    for peer in peers:
        if peer.claim_id == claim_id:
            continue
        decision = compare_knowledge_identity(
            target.value,
            target.detail,
            peer.value,
            peer.detail,
            left_slot=target.slot,
            right_slot=peer.slot,
        )
        if decision.label != "same_target":
            continue
        union(claim_id, peer.claim_id)
        for mapped_id in (claim_id, peer.claim_id):
            reasons[mapped_id] = (decision.reason, decision.confidence, "equivalent")

    root = find(claim_id)
    members = [row for row in peers if find(row.claim_id) == root]
    fingerprints = {
        row.claim_id: fingerprint_claim(value=row.value, detail=row.detail, slot=row.slot)
        for row in members
    }
    knowledge_id = min(fingerprints[row.claim_id].identity_id for row in members)
    representative = next(
        row for row in members if fingerprints[row.claim_id].identity_id == knowledge_id
    )
    persist_knowledge_identity(connection, fingerprints[representative.claim_id], created_at=stamp)
    merged = len(members) > 1
    mappings: list[KnowledgeIdentityMapping] = []
    for member in members:
        reason, confidence, decision = reasons.get(
            member.claim_id,
            ("no equivalent peer; claim-scoped identity", "high", "singleton"),
        )
        if not merged:
            reason, confidence, decision = (
                "no equivalent peer; claim-scoped identity",
                "high",
                "singleton",
            )
        mappings.append(
            map_claim_to_knowledge(
                connection,
                claim_id=member.claim_id,
                knowledge_id=knowledge_id,
                reason=reason,
                confidence=confidence,
                decision=decision,
                created_at=stamp,
            )
        )
    return tuple(sorted(mappings, key=lambda item: item.claim_id))


def rebuild_knowledge_identities(
    connection: sqlite3.Connection,
    *,
    claim_ids: Sequence[str] | None = None,
    created_at: int | None = None,
) -> tuple[KnowledgeIdentityMapping, ...]:
    """Recompute claim→knowledge maps. Observation / claim rows are not deleted."""
    records = _load_claim_records(connection, claim_ids)
    if not records:
        return ()
    stamp = int(time.time()) if created_at is None else created_at
    fingerprints = {
        record.claim_id: fingerprint_claim(
            value=record.value, detail=record.detail, slot=record.slot
        )
        for record in records
    }
    parent = {record.claim_id: record.claim_id for record in records}

    def find(claim_id: str) -> str:
        while parent[claim_id] != claim_id:
            parent[claim_id] = parent[parent[claim_id]]
            claim_id = parent[claim_id]
        return claim_id

    def union(left_id: str, right_id: str) -> None:
        left_root, right_root = find(left_id), find(right_id)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    reasons: dict[str, tuple[str, str, str]] = {}
    ordered = sorted(records, key=lambda item: item.claim_id)
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            decision = compare_knowledge_identity(
                left.value,
                left.detail,
                right.value,
                right.detail,
                left_slot=left.slot,
                right_slot=right.slot,
            )
            if decision.label != "same_target":
                continue
            union(left.claim_id, right.claim_id)
            for claim_id in (left.claim_id, right.claim_id):
                reasons[claim_id] = (decision.reason, decision.confidence, "equivalent")

    components: dict[str, list[_ClaimRecord]] = {}
    for record in ordered:
        components.setdefault(find(record.claim_id), []).append(record)

    mappings: list[KnowledgeIdentityMapping] = []
    for members in components.values():
        member_ids = [fingerprints[member.claim_id].identity_id for member in members]
        knowledge_id = min(member_ids)
        representative = next(
            member
            for member in members
            if fingerprints[member.claim_id].identity_id == knowledge_id
        )
        persist_knowledge_identity(
            connection, fingerprints[representative.claim_id], created_at=stamp
        )
        merged = len(members) > 1
        for member in members:
            reason, confidence, decision = reasons.get(
                member.claim_id,
                ("no equivalent peer; claim-scoped identity", "high", "singleton"),
            )
            if not merged:
                reason, confidence, decision = (
                    "no equivalent peer; claim-scoped identity",
                    "high",
                    "singleton",
                )
            mappings.append(
                map_claim_to_knowledge(
                    connection,
                    claim_id=member.claim_id,
                    knowledge_id=knowledge_id,
                    reason=reason,
                    confidence=confidence,
                    decision=decision,
                    created_at=stamp,
                )
            )
    return tuple(sorted(mappings, key=lambda item: item.claim_id))


def _hard_guard(
    left: KnowledgeIdentityFingerprint,
    right: KnowledgeIdentityFingerprint,
) -> tuple[IdentityLabel, str, Confidence] | None:
    if left.slot != right.slot:
        return ("different_target", "claim slots differ", "high")
    if left.stable_ids and right.stable_ids and left.stable_ids != right.stable_ids:
        return ("different_target", "stable identifiers differ", "high")
    if bool(left.stable_ids) != bool(right.stable_ids):
        return (
            "uncertain",
            "stable identifiers are present on only one side; abstaining",
            "low",
        )
    if left.versions != right.versions and (left.versions or right.versions):
        return ("different_target", "version identifiers differ", "high")
    if left.numbers != right.numbers and (left.numbers or right.numbers):
        return ("different_target", "numeric facts differ", "high")
    if left.dates != right.dates and (left.dates or right.dates):
        return ("different_target", "dates differ", "high")
    if left.negated != right.negated:
        return ("different_target", "polarity or negation differs", "high")
    return None


def _fingerprint_canonical(
    canonical: CanonicalClaim,
    *,
    slot: str,
) -> KnowledgeIdentityFingerprint:
    value_tokens = tuple(sorted(canonical.value.tokens))
    detail_tokens = tuple(sorted(canonical.detail.tokens))
    numbers = tuple(sorted(set(canonical.value.numbers) | set(canonical.detail.numbers)))
    versions = tuple(sorted(set(canonical.value.versions) | set(canonical.detail.versions)))
    dates = tuple(
        sorted(
            set(_DATE_TOKEN_RE.findall(canonical.value.text))
            | set(_DATE_TOKEN_RE.findall(canonical.detail.text))
        )
    )
    stable_ids = _stable_ids(canonical.value.text, canonical.detail.text)
    negated = canonical.value.negated or canonical.detail.negated
    payload = {
        "version": KNOWLEDGE_IDENTITY_VERSION,
        "slot": slot,
        "value_tokens": value_tokens,
        "detail_tokens": detail_tokens,
        "numbers": numbers,
        "versions": versions,
        "dates": dates,
        "stable_ids": stable_ids,
        "negated": negated,
    }
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    identity_id = f"knid_{hashlib.sha256(payload_json.encode()).hexdigest()[:24]}"
    return KnowledgeIdentityFingerprint(
        identity_id=identity_id,
        slot=slot,
        value_tokens=value_tokens,
        detail_tokens=detail_tokens,
        numbers=numbers,
        versions=versions,
        dates=dates,
        stable_ids=stable_ids,
        negated=negated,
        version=KNOWLEDGE_IDENTITY_VERSION,
        payload_json=payload_json,
    )


def _prepare_identity_text(text: str) -> str:
    """Drop source-framing prefixes so cross-source restatements can match."""
    output = unicodedata.normalize("NFKC", text).strip()
    lowered = output.casefold()
    for prefix in _SOURCE_FRAME_PREFIXES:
        if lowered.startswith(prefix):
            return output[len(prefix) :].strip()
    return output


def _stable_ids(*texts: str) -> tuple[str, ...]:
    found: set[str] = set()
    for text in texts:
        found.update(match.casefold() for match in _CVE_RE.findall(text))
        found.update(match.casefold() for match in _GHSA_RE.findall(text))
    return tuple(sorted(found))


def _load_claim_records(
    connection: sqlite3.Connection,
    claim_ids: Sequence[str] | None,
) -> list[_ClaimRecord]:
    rows = connection.execute(
        """
        SELECT id, slot, value_text, detail_text
        FROM state_claims
        ORDER BY id
        """
    ).fetchall()
    if claim_ids is not None:
        wanted = set(claim_ids)
        if not wanted:
            return []
        rows = [row for row in rows if row["id"] in wanted]
    return [
        _ClaimRecord(
            claim_id=str(row["id"]),
            slot=str(row["slot"]),
            value=str(row["value_text"]),
            detail=str(row["detail_text"]),
        )
        for row in rows
    ]


# visibility_for_state is reused by tests that compose identity + evidence.
__all__ = (
    "CLAIM_KNOWLEDGE_MAP_TABLE",
    "KNOWLEDGE_IDENTITY_TABLE",
    "KNOWLEDGE_IDENTITY_TABLES",
    "KNOWLEDGE_IDENTITY_VERSION",
    "KnowledgeIdentityDecision",
    "KnowledgeIdentityFingerprint",
    "KnowledgeIdentityMapping",
    "claims_for_knowledge_id",
    "compare_knowledge_identity",
    "ensure_claim_knowledge_mapping",
    "fingerprint_claim",
    "identity_may_hide",
    "list_knowledge_evidence_for_identity",
    "map_claim_to_knowledge",
    "persist_knowledge_identity",
    "attach_knowledge_identity_for_claim",
    "rebuild_knowledge_identities",
    "replay_knowledge_state_for_identity",
    "resolve_claim_knowledge_id",
    "resolve_claim_knowledge_ids",
    "visibility_for_identity",
)
