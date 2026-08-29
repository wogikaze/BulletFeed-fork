from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.database import Database
from app.db.event_identity_schema import ensure_event_identity_schema
from app.db.state_ledger_schema import STATE_LEDGER_SCHEMA
from app.services.claim_semantics import canonicalize_text
from app.services.event_concepts import EventConceptExtraction, extract_event_concepts
from app.services.semantic_equivalence import (
    DEFAULT_ENTITY_ALIASES,
    compare_semantic_equivalence,
)

CoreferenceLabel = Literal["same_event", "different_event", "uncertain"]
Confidence = Literal["high", "medium", "low"]
COREFERENCE_VERSION = "event-coreference-v2"
_STRUCTURED_FAMILIES = {"statuspage", "github_release", "github_advisory", "osv"}
_ADVISORY_PREFIXES = ("cve:", "ghsa:", "osv:")
_SPLIT_CONCEPT_TYPES = frozenset({"framework_library_package", "language_runtime"})
_IDENTITY_CONCEPT_TYPES = frozenset(
    {
        "product_service",
        "language_runtime",
        "framework_library_package",
        "company_project",
        "api_protocol",
        "repository",
        "vulnerability_advisory",
    }
)
_IDENTITY_GUARD_NAMES = frozenset({"version", "stable_id", "region"})
_REGION_RE = re.compile(r"\b(?:us|eu|ap|af|sa|me|cn)-[a-z0-9]+-\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class CoreferencePolicy:
    same_event_overlap: float = 0.75
    different_event_overlap: float = 0.30
    same_event_max_days: float = 14.0
    different_event_min_days: float = 60.0
    candidate_recent_days: float = 7.0
    candidate_limit: int = 20
    version: str = COREFERENCE_VERSION

    @property
    def replay_version(self) -> str:
        return (
            f"{self.version}[same={self.same_event_overlap:.2f},"
            f"different={self.different_event_overlap:.2f},"
            f"same_days={self.same_event_max_days:g},"
            f"different_days={self.different_event_min_days:g},"
            f"limit={self.candidate_limit}]"
        )


DEFAULT_COREFERENCE_POLICY = CoreferencePolicy()


@dataclass(frozen=True)
class CoreferenceInput:
    source_type: str
    source_key: str
    source_event_id: str
    title: str
    subject: str
    valid_at: str

    @property
    def alias_key(self) -> str:
        return identity_alias_key(self.source_type, self.source_key, self.source_event_id)


@dataclass(frozen=True)
class EventCandidate:
    event_id: str
    source_type: str
    source_key: str
    source_event_id: str
    title: str
    created_at: str
    latest_value: str
    latest_detail: str
    latest_valid_at: str
    score: float


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[EventCandidate, ...]
    considered: int

    @property
    def size(self) -> int:
        return len(self.candidates)


@dataclass(frozen=True)
class CoreferenceDecision:
    label: CoreferenceLabel
    reason: str
    confidence: Confidence
    candidate_event_id: str | None = None
    score: float = 0.0
    version: str = COREFERENCE_VERSION
    hard_guards: tuple[str, ...] = ()


class EventCoreferenceEngine:
    def __init__(
        self,
        database: Database,
        *,
        policy: CoreferencePolicy = DEFAULT_COREFERENCE_POLICY,
        candidate_limit: int | None = None,
    ) -> None:
        resolved_limit = policy.candidate_limit if candidate_limit is None else candidate_limit
        if resolved_limit < 1:
            raise ValueError("candidate_limit must be positive")
        self._database = database
        self._policy = policy
        self._candidate_limit = resolved_limit
        with database.connect() as connection:
            connection.executescript(STATE_LEDGER_SCHEMA)
        ensure_event_identity_schema(database)

    @property
    def decision_version(self) -> str:
        if self._candidate_limit == self._policy.candidate_limit:
            return self._policy.replay_version
        return (
            f"{self._policy.version}[same={self._policy.same_event_overlap:.2f},"
            f"different={self._policy.different_event_overlap:.2f},"
            f"same_days={self._policy.same_event_max_days:g},"
            f"different_days={self._policy.different_event_min_days:g},"
            f"limit={self._candidate_limit}]"
        )

    def resolve(self, value: CoreferenceInput, *, user_id: str | None = None) -> CoreferenceDecision:
        alias = self._resolve_alias_record(value.alias_key, user_id=user_id)
        if alias is not None:
            event_id, decision_version = alias
            return _decision(
                "same_event",
                "stable source identity is mapped by an audited alias",
                "high",
                candidate_event_id=event_id,
                score=1.0,
                version=decision_version,
            )

        candidate_set = self.retrieve_candidates(value, user_id=user_id)
        decisions = [(candidate, self.compare(value, candidate)) for candidate in candidate_set.candidates]
        same = [item for item in decisions if item[1].label == "same_event"]
        if same:
            candidate, decision = max(same, key=lambda item: (item[1].score, item[0].event_id))
            return _decision(
                decision.label,
                decision.reason,
                decision.confidence,
                candidate_event_id=candidate.event_id,
                score=decision.score,
                version=decision.version,
                hard_guards=decision.hard_guards,
            )
        uncertain = [item for item in decisions if item[1].label == "uncertain"]
        if uncertain:
            candidate, decision = max(uncertain, key=lambda item: (item[1].score, item[0].event_id))
            return _decision(
                "uncertain",
                decision.reason,
                "low",
                candidate_event_id=candidate.event_id,
                score=decision.score,
                version=decision.version,
                hard_guards=decision.hard_guards,
            )
        return _decision(
            "different_event",
            "no candidate met the conservative same-event threshold",
            "medium",
            version=self.decision_version,
        )

    def retrieve_candidates(
        self,
        value: CoreferenceInput,
        *,
        user_id: str | None = None,
    ) -> CandidateSet:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.*,
                       COALESCE(c.value_text, '') AS latest_value,
                       COALESCE(c.detail_text, '') AS latest_detail,
                       COALESCE(c.valid_at, e.created_at) AS latest_valid_at
                FROM ledger_events e
                LEFT JOIN state_claims c ON c.id = (
                    SELECT c2.id FROM state_claims c2
                    WHERE c2.event_id = e.id
                    ORDER BY c2.valid_at DESC, c2.source_updated_at DESC, c2.id DESC
                    LIMIT 1
                )
                ORDER BY e.created_at DESC, e.id
                LIMIT 250
                """
            ).fetchall()
            considered = 0
            candidates: list[EventCandidate] = []
            incoming_features = _mention_features(
                source_type=value.source_type,
                source_key=value.source_key,
                title=value.title,
                subject=value.subject,
            )
            for row in rows:
                if not self._visible(connection, row, user_id=user_id):
                    continue
                considered += 1
                score = self._candidate_score(value, row, incoming_features)
                if score < 0.2 and not self._exact_source_scope(value, row):
                    continue
                candidates.append(
                    EventCandidate(
                        event_id=row["id"],
                        source_type=row["source_type"],
                        source_key=row["source_key"],
                        source_event_id=row["source_event_id"],
                        title=row["title"],
                        created_at=row["created_at"],
                        latest_value=row["latest_value"],
                        latest_detail=row["latest_detail"],
                        latest_valid_at=row["latest_valid_at"],
                        score=score,
                    )
                )
        candidates.sort(key=lambda candidate: (-candidate.score, candidate.event_id))
        return CandidateSet(tuple(candidates[: self._candidate_limit]), considered)

    def compare(self, value: CoreferenceInput, candidate: EventCandidate) -> CoreferenceDecision:
        return compare_event_mentions(
            value,
            candidate,
            policy=self._policy,
            decision_version=self.decision_version,
        )

    def record_alias(
        self,
        alias_key: str,
        event_id: str,
        *,
        reason: str,
        created_at: str,
        decision_version: str = "manual-v1",
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO event_identity_aliases (
                    alias_key, event_id, reason, decision_version, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(alias_key) DO UPDATE SET
                    event_id = excluded.event_id,
                    reason = excluded.reason,
                    decision_version = excluded.decision_version,
                    created_at = excluded.created_at
                """,
                (alias_key, event_id, reason, decision_version, created_at),
            )

    def resolve_alias(self, alias_key: str, *, user_id: str | None = None) -> str | None:
        record = self._resolve_alias_record(alias_key, user_id=user_id)
        return record[0] if record is not None else None

    def _resolve_alias_record(
        self,
        alias_key: str,
        *,
        user_id: str | None,
    ) -> tuple[str, str] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT a.event_id, a.decision_version, e.source_key
                FROM event_identity_aliases a
                JOIN ledger_events e ON e.id = a.event_id
                WHERE a.alias_key = ?
                """,
                (alias_key,),
            ).fetchone()
            if row is None or not self._visible(connection, row, user_id=user_id):
                return None
        return row["event_id"], row["decision_version"]

    @staticmethod
    def _exact_source_scope(value: CoreferenceInput, row) -> bool:
        return value.source_type == row["source_type"] and value.source_key == row["source_key"]

    def _candidate_score(self, value: CoreferenceInput, row, incoming: _MentionFeatures) -> float:
        existing = _mention_features(
            source_type=row["source_type"],
            source_key=row["source_key"],
            title=row["title"],
            subject=f"{row['latest_value']} {row['latest_detail']}",
        )
        score = _token_overlap(incoming.tokens, existing.tokens)
        if value.source_key and value.source_key == row["source_key"]:
            score += 0.15
        if _days_apart(value.valid_at, row["latest_valid_at"]) <= self._policy.candidate_recent_days:
            score += 0.1
        if incoming.advisory_ids and existing.advisory_ids:
            if incoming.advisory_ids & existing.advisory_ids:
                score += 0.5
        elif incoming.identity_concepts and incoming.identity_concepts & existing.identity_concepts:
            score += 0.2
        return min(1.0, score)

    @staticmethod
    def _visible(connection, row, *, user_id: str | None) -> bool:
        event_id = row["event_id"] if "event_id" in row.keys() else row["id"]
        visibility = connection.execute(
            "SELECT restricted FROM event_visibility WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if visibility is not None and bool(visibility["restricted"]):
            if user_id is None:
                return False
            grant = connection.execute(
                """
                SELECT 1 FROM event_user_access
                WHERE event_id = ? AND user_id = ? AND expires_at > ?
                """,
                (event_id, user_id, int(time.time())),
            ).fetchone()
            return grant is not None

        private_watch = connection.execute(
            "SELECT 1 FROM github_repo_watches WHERE full_name = ? AND private = 1 LIMIT 1",
            (row["source_key"],),
        ).fetchone()
        if private_watch is None:
            return True
        if user_id is None:
            return False
        own_watch = connection.execute(
            """
            SELECT 1 FROM github_repo_watches
            WHERE full_name = ? AND user_id = ? AND private = 1 AND selected = 1
            LIMIT 1
            """,
            (row["source_key"], user_id),
        ).fetchone()
        return own_watch is not None


def compare_event_mentions(
    value: CoreferenceInput,
    candidate: EventCandidate,
    *,
    policy: CoreferencePolicy = DEFAULT_COREFERENCE_POLICY,
    decision_version: str | None = None,
) -> CoreferenceDecision:
    """Decide same_event / different_event / uncertain from meaning-based evidence.

    Structured identity is strongest. Semantic equivalence and Event concepts are
    evidence only: they cannot override a hard identity guard. Ambiguous evidence
    prefers a false split (uncertain / different_event) over a false merge.
    """
    version = decision_version or policy.replay_version
    if (
        value.source_type == candidate.source_type
        and value.source_key == candidate.source_key
        and value.source_event_id == candidate.source_event_id
    ):
        return _decision(
            "same_event",
            "structured source identity is identical",
            "high",
            candidate_event_id=candidate.event_id,
            score=1.0,
            version=version,
        )
    if (
        value.source_type == candidate.source_type
        and value.source_key == candidate.source_key
        and value.source_type in _STRUCTURED_FAMILIES
        and value.source_event_id != candidate.source_event_id
    ):
        return _decision(
            "different_event",
            "distinct structured IDs in the same source scope are a hard negative",
            "high",
            candidate_event_id=candidate.event_id,
            score=0.0,
            version=version,
        )

    incoming = _mention_features(
        source_type=value.source_type,
        source_key=value.source_key,
        title=value.title,
        subject=value.subject,
    )
    existing = _mention_features(
        source_type=candidate.source_type,
        source_key=candidate.source_key,
        title=candidate.title,
        subject=f"{candidate.latest_value} {candidate.latest_detail}",
    )
    days = _days_apart(value.valid_at, candidate.latest_valid_at)
    overlap = _token_overlap(incoming.tokens, existing.tokens)
    scope_bonus = 0.15 if value.source_key and value.source_key == candidate.source_key else 0.0
    score = min(1.0, overlap + scope_bonus + (0.1 if days <= 2 else 0.0))

    identity_guards = _identity_hard_guards(incoming, existing)
    if identity_guards:
        return _decision(
            "different_event",
            f"hard identity guard ({', '.join(identity_guards)})",
            "high",
            candidate_event_id=candidate.event_id,
            score=0.0,
            version=version,
            hard_guards=identity_guards,
        )

    shared_advisories = incoming.advisory_ids & existing.advisory_ids
    if shared_advisories:
        return _decision(
            "same_event",
            "shared advisory identifier is a deterministic event identity",
            "high",
            candidate_event_id=candidate.event_id,
            score=max(score, 0.98),
            version=version,
        )

    incoming_text = " ".join(part for part in (value.title, value.subject) if part)
    existing_text = " ".join(
        part
        for part in (candidate.title, candidate.latest_value, candidate.latest_detail)
        if part
    )
    equivalence = compare_semantic_equivalence(
        incoming_text,
        incoming_text,
        existing_text,
        existing_text,
        entity_aliases=DEFAULT_ENTITY_ALIASES,
    )
    claim_guards = equivalence.hard_guards
    blocked_by_guards = bool(claim_guards)

    incoming_title = canonicalize_text(value.title, entity_aliases=DEFAULT_ENTITY_ALIASES)
    existing_title = canonicalize_text(candidate.title, entity_aliases=DEFAULT_ENTITY_ALIASES)
    if (
        incoming_title.text == existing_title.text
        and len(set(incoming_title.tokens)) >= 2
        and days <= policy.different_event_min_days
        and not incoming.region_ids.symmetric_difference(existing.region_ids)
    ):
        return _decision(
            "same_event",
            "specific canonical titles match within the extended lifecycle window",
            "medium",
            candidate_event_id=candidate.event_id,
            score=0.95,
            version=version,
            hard_guards=claim_guards,
        )

    disjoint_products = (
        incoming.split_concepts
        and existing.split_concepts
        and not incoming.split_concepts & existing.split_concepts
    )
    if disjoint_products:
        return _decision(
            "different_event",
            "event concepts name distinct products or runtimes",
            "high",
            candidate_event_id=candidate.event_id,
            score=score,
            version=version,
            hard_guards=claim_guards,
        )

    exclusive_conflict = _near_copy_conflict(incoming.tokens, existing.tokens, overlap)
    if (
        not blocked_by_guards
        and not exclusive_conflict
        and equivalence.label == "equivalent"
        and equivalence.confidence in {"high", "medium"}
        and days <= policy.same_event_max_days
    ):
        return _decision(
            "same_event",
            f"semantic equivalence evidence: {equivalence.reason}",
            "medium",
            candidate_event_id=candidate.event_id,
            score=max(score, 0.88),
            version=version,
        )

    if (
        incoming.identity_concepts
        and incoming.identity_concepts & existing.identity_concepts
        and days <= policy.same_event_max_days
        and overlap >= 0.25
        and not blocked_by_guards
        and not exclusive_conflict
        and equivalence.label != "not_equivalent"
    ):
        shared = sorted(incoming.identity_concepts & existing.identity_concepts)
        return _decision(
            "same_event",
            f"shared event concepts ({', '.join(shared[:4])}) within the event time window",
            "medium",
            candidate_event_id=candidate.event_id,
            score=max(score, 0.86),
            version=version,
        )

    if (
        overlap >= policy.same_event_overlap
        and days <= policy.same_event_max_days
        and "version" not in claim_guards
        and "stable_id" not in claim_guards
        and "date" not in claim_guards
        and not exclusive_conflict
        and not (incoming.region_ids and existing.region_ids and incoming.region_ids != existing.region_ids)
    ):
        return _decision(
            "same_event",
            "subject/entity tokens strongly overlap within the event time window",
            "medium",
            candidate_event_id=candidate.event_id,
            score=score,
            version=version,
            hard_guards=claim_guards,
        )
    if overlap <= policy.different_event_overlap or days > policy.different_event_min_days:
        reason = "subject overlap or event time window is insufficient"
        if claim_guards:
            reason = f"{reason}; hard guard ({', '.join(claim_guards)}) blocked a merge"
        return _decision(
            "different_event",
            reason,
            "medium",
            candidate_event_id=candidate.event_id,
            score=score,
            version=version,
            hard_guards=claim_guards,
        )
    reason = "candidate evidence is plausible but below the safe merge threshold"
    if blocked_by_guards:
        reason = (
            f"{reason}; hard guard ({', '.join(claim_guards)}) "
            "is evidence against merge, not an override of stronger identity"
        )
    elif equivalence.label == "not_equivalent":
        reason = f"{reason}; semantic equivalence evidence is not_equivalent"
    return _decision(
        "uncertain",
        reason,
        "low",
        candidate_event_id=candidate.event_id,
        score=score,
        version=version,
        hard_guards=claim_guards,
    )


def identity_alias_key(source_type: str, source_key: str, source_event_id: str) -> str:
    return "|".join((source_type, source_key, source_event_id))


@dataclass(frozen=True)
class _MentionFeatures:
    tokens: tuple[str, ...]
    versions: tuple[str, ...]
    advisory_ids: frozenset[str]
    region_ids: frozenset[str]
    identity_concepts: frozenset[str]
    split_concepts: frozenset[str]


def _mention_features(
    *,
    source_type: str,
    source_key: str,
    title: str,
    subject: str,
) -> _MentionFeatures:
    combined = f"{title} {subject}".strip()
    canonical = canonicalize_text(combined, entity_aliases=DEFAULT_ENTITY_ALIASES)
    extraction = extract_event_concepts(
        {
            "source_type": source_type,
            "source_key": source_key,
            "title": title,
            "summary": subject,
        }
    )
    return _MentionFeatures(
        tokens=canonical.tokens,
        versions=canonical.versions,
        advisory_ids=_advisory_ids(extraction, combined),
        region_ids=frozenset(match.casefold() for match in _REGION_RE.findall(combined)),
        identity_concepts=_concepts_of(extraction, _IDENTITY_CONCEPT_TYPES),
        split_concepts=_concepts_of(extraction, _SPLIT_CONCEPT_TYPES),
    )


def _advisory_ids(extraction: EventConceptExtraction, text: str) -> frozenset[str]:
    found = {
        concept.stable_id.casefold()
        for concept in extraction.concepts
        if concept.stable_id and concept.stable_id.casefold().startswith(_ADVISORY_PREFIXES)
    }
    canonical = canonicalize_text(text, entity_aliases=DEFAULT_ENTITY_ALIASES)
    for token in (*canonical.tokens, *canonical.versions, text):
        key = token.casefold()
        if key.startswith("cve-"):
            found.add(f"cve:{key}")
        elif key.startswith("ghsa-"):
            found.add(f"ghsa:{key}")
        elif key.startswith("osv-"):
            found.add(f"osv:{key}")
    return frozenset(found)


def _concepts_of(extraction: EventConceptExtraction, types: frozenset[str]) -> frozenset[str]:
    return frozenset(
        concept.concept_id
        for concept in extraction.concepts
        if concept.concept_type in types and concept.weight >= 0.7
    )


def _identity_hard_guards(incoming: _MentionFeatures, existing: _MentionFeatures) -> tuple[str, ...]:
    guards: list[str] = []
    if incoming.versions != existing.versions and incoming.versions and existing.versions:
        guards.append("version")
    if incoming.advisory_ids and existing.advisory_ids:
        if incoming.advisory_ids.isdisjoint(existing.advisory_ids):
            guards.append("stable_id")
    if incoming.region_ids and existing.region_ids and incoming.region_ids != existing.region_ids:
        guards.append("region")
    return tuple(dict.fromkeys(item for item in guards if item in _IDENTITY_GUARD_NAMES))


def _near_copy_conflict(left: tuple[str, ...], right: tuple[str, ...], overlap: float) -> bool:
    """Same-words-different-fact: high overlap with a swapped slot must not merge."""
    left_only = set(left) - set(right)
    right_only = set(right) - set(left)
    return bool(left_only and right_only and overlap >= 0.55 and len(left_only) <= 3 and len(right_only) <= 3)


def _token_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 1.0
    return len(left_set & right_set) / len(union)


def _days_apart(left: str, right: str) -> float:
    try:
        left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
        if left_dt.tzinfo is None:
            left_dt = left_dt.replace(tzinfo=UTC)
        if right_dt.tzinfo is None:
            right_dt = right_dt.replace(tzinfo=UTC)
        return abs((left_dt - right_dt).total_seconds()) / 86400
    except ValueError:
        return 9999.0


def _decision(
    label: CoreferenceLabel,
    reason: str,
    confidence: Confidence,
    *,
    candidate_event_id: str | None = None,
    score: float = 0.0,
    version: str | None = None,
    hard_guards: tuple[str, ...] = (),
) -> CoreferenceDecision:
    return CoreferenceDecision(
        label,
        reason,
        confidence,
        candidate_event_id=candidate_event_id,
        score=score,
        version=version or DEFAULT_COREFERENCE_POLICY.replay_version,
        hard_guards=hard_guards,
    )
