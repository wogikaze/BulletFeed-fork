"""Cross-source repetition control (Known-06 / cross-source-suppress-v1).

Same known facts from later sources collapse onto one card. New evidence,
added detail, and corrections still surface. Hide is allowed only after
the Known-05 conservative guard says so. Uncertain identity never hides.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.schemas.common import SourceEvidence
from app.services.false_suppression import (
    POLICY_VERSION as GUARD_VERSION,
)
from app.services.false_suppression import (
    SuppressionDecision,
    decide_suppression,
)
from app.services.knowledge_evidence import VisibilityAction
from app.services.knowledge_identity import (
    KNOWLEDGE_IDENTITY_VERSION,
    KnowledgeIdentityDecision,
    compare_knowledge_identity,
    fingerprint_claim,
    identity_may_hide,
)
from app.services.semantic_delta import ClaimSnapshot, judge_revision

POLICY_VERSION: Final = "cross-source-suppress-v1"
GUARD_POLICY_VERSION: Final = GUARD_VERSION

SURFACING_REVISIONS: Final[frozenset[str]] = frozenset(
    {
        "NEW_FACT",
        "DETAIL",
        "STATE_UPDATE",
        "CORRECTION",
        "UNRESOLVED_CONTRADICTION",
    }
)
COLLAPSE_REVISIONS: Final[frozenset[str]] = frozenset({"NON_NOVEL"})

AdditionalSourceRole = Literal["restatement", "syndication", "independent_confirmation"]
CandidateRole = Literal["displayed", "additional_source", "hidden"]


@dataclass(frozen=True)
class SourceCandidate:
    """One source-backed fact at projection/ranking time."""

    candidate_id: str
    source_id: str
    publisher: str
    kind: str
    title: str
    url: str
    published_at: str
    retrieved_at: str
    evidence: str
    value: str
    detail: str = ""
    slot: str = ""
    revision_class: str | None = None
    dependence_key: str | None = None
    knowledge_state: str = "unknown"
    knowledge_confidence: str = "none"
    importance_level: str | None = None
    stale_exposure: bool = False
    identity_label: str | None = None
    identity_confidence: str | None = None
    equivalence_label: str | None = None

    def dependence(self) -> str:
        return self.dependence_key or f"candidate:{self.candidate_id}"


@dataclass(frozen=True)
class AdditionalSource:
    candidate_id: str
    source_id: str
    publisher: str
    kind: str
    title: str
    url: str
    published_at: str
    retrieved_at: str
    evidence: str
    dependence_key: str
    role: AdditionalSourceRole
    identity_id: str | None
    reason: str

    def to_source_evidence(self) -> SourceEvidence:
        return SourceEvidence.model_construct(
            publisher=self.publisher,
            kind=self.kind,
            title=self.title,
            url=self.url,
            published_at=self.published_at,
            retrieved_at=self.retrieved_at,
            evidence=self.evidence,
        )


@dataclass(frozen=True)
class ProjectedCard:
    displayed_id: str
    action: VisibilityAction
    may_hide: bool
    reason: str
    version: str
    knowledge_id: str | None
    additional_sources: tuple[AdditionalSource, ...]
    hidden_ids: tuple[str, ...]
    independent_evidence_count: int
    guard: SuppressionDecision
    records: tuple[dict[str, str | bool | None], ...]

    def provenance(self) -> tuple[SourceEvidence, ...]:
        """Canonical item plus collapsed sources. Provenance stays reachable."""
        return tuple(item.to_source_evidence() for item in self.additional_sources)


@dataclass(frozen=True)
class ProjectionBatch:
    cards: tuple[ProjectedCard, ...]
    displayed_ids: tuple[str, ...]
    additional_source_ids: tuple[str, ...]
    hidden_ids: tuple[str, ...]
    version: str


def normalize_revision(revision_class: str | None) -> str | None:
    if revision_class is None:
        return None
    return revision_class.strip().upper() or None


def must_surface_revision(revision_class: str | None) -> bool:
    return normalize_revision(revision_class) in SURFACING_REVISIONS


def resolve_identity(
    left: SourceCandidate,
    right: SourceCandidate,
) -> KnowledgeIdentityDecision:
    """Use #50 knowledge identity. Supplied labels are fallbacks only."""
    if left.value or right.value or left.detail or right.detail:
        return compare_knowledge_identity(
            left.value,
            left.detail,
            right.value,
            right.detail,
            left_slot=left.slot,
            right_slot=right.slot,
        )
    label = right.identity_label or left.identity_label or "uncertain"
    confidence = right.identity_confidence or left.identity_confidence or "low"
    if label == "same_target":
        shared = "supplied-same-target"
        return KnowledgeIdentityDecision(
            "same_target",
            "supplied identity label is same_target",
            confidence if confidence in {"high", "medium", "low"} else "low",
            KNOWLEDGE_IDENTITY_VERSION,
            shared,
            shared,
            shared,
        )
    if label == "different_target":
        return KnowledgeIdentityDecision(
            "different_target",
            "supplied identity label is different_target",
            "high",
            KNOWLEDGE_IDENTITY_VERSION,
            "supplied-left",
            "supplied-right",
            None,
        )
    return KnowledgeIdentityDecision(
        "uncertain",
        "supplied identity is uncertain; abstaining",
        "low",
        KNOWLEDGE_IDENTITY_VERSION,
        "supplied-left",
        "supplied-right",
        None,
    )


def resolve_revision(
    canonical: SourceCandidate,
    candidate: SourceCandidate,
    identity: KnowledgeIdentityDecision,
) -> str | None:
    explicit = normalize_revision(candidate.revision_class)
    if explicit is not None:
        return explicit
    if identity.label == "same_target" and identity_may_hide(identity):
        return "NON_NOVEL"
    if identity.label == "uncertain":
        return None
    decision = judge_revision(
        ClaimSnapshot(canonical.value, canonical.detail, canonical.published_at),
        ClaimSnapshot(candidate.value, candidate.detail, candidate.published_at),
    )
    return decision.revision_type


def decide_guard(
    candidate: SourceCandidate,
    *,
    identity: KnowledgeIdentityDecision | None = None,
    revision_class: str | None = None,
    equivalence_label: str | None = None,
) -> SuppressionDecision:
    """Known-05 runs first. Cross-source collapse may not invent a hide."""
    return decide_suppression(
        knowledge_state=candidate.knowledge_state,
        knowledge_confidence=candidate.knowledge_confidence,
        identity_label=candidate.identity_label if identity is None else None,
        identity_confidence=candidate.identity_confidence if identity is None else None,
        equivalence_label=equivalence_label or candidate.equivalence_label,
        revision_class=revision_class or candidate.revision_class,
        importance_level=candidate.importance_level,
        stale_exposure=candidate.stale_exposure,
        identity=identity,
    )


def additional_source_role(
    canonical: SourceCandidate,
    candidate: SourceCandidate,
) -> AdditionalSourceRole:
    if canonical.dependence() == candidate.dependence():
        return "syndication"
    return "independent_confirmation"


def independent_evidence_count(candidates: Sequence[SourceCandidate]) -> int:
    """Source count is not independent evidence count."""
    return len({item.dependence() for item in candidates})


def project_candidates(candidates: Sequence[SourceCandidate]) -> ProjectionBatch:
    """Collapse same-fact cards after the hide guard. Unknowns stay visible."""
    groups: list[_Group] = []
    for candidate in _sorted(candidates):
        placed = False
        leftover: tuple[KnowledgeIdentityDecision, str | None] | None = None
        for group in groups:
            identity = resolve_identity(group.canonical, candidate)
            revision = resolve_revision(group.canonical, candidate, identity)
            if _must_keep_separate(identity, revision):
                leftover = (identity, revision)
                continue
            guard = decide_guard(
                candidate,
                identity=identity,
                revision_class=revision,
                equivalence_label=_equivalence_for(identity),
            )
            if guard.may_hide:
                group.hide(candidate, identity, guard, revision)
            else:
                group.attach(candidate, identity, guard, revision)
            placed = True
            break
        if placed:
            continue
        if leftover is not None:
            identity, revision = leftover
        else:
            identity = _self_identity(candidate)
            revision = normalize_revision(candidate.revision_class)
        guard = decide_guard(
            candidate,
            identity=identity,
            revision_class=revision,
            equivalence_label=_equivalence_for(identity),
        )
        if leftover is not None and _must_keep_separate(*leftover) and guard.may_hide:
            # Refusing to collapse must not become hide. Re-ask #53 as new evidence.
            separated = _separate_identity(leftover[0])
            guard = decide_guard(
                candidate,
                identity=separated,
                revision_class=revision,
                equivalence_label=_equivalence_for(separated),
            )
        groups.append(_Group.open(candidate, identity, guard, revision))

    cards = tuple(group.to_card() for group in groups)
    displayed = tuple(card.displayed_id for card in cards if card.action != "hide")
    additional = tuple(
        source.candidate_id for card in cards for source in card.additional_sources
    )
    hidden = tuple(candidate_id for card in cards for candidate_id in card.hidden_ids)
    return ProjectionBatch(
        cards=cards,
        displayed_ids=displayed,
        additional_source_ids=additional,
        hidden_ids=hidden,
        version=POLICY_VERSION,
    )


def record_projection(batch: ProjectionBatch) -> tuple[dict[str, str | bool | None], ...]:
    records: list[dict[str, str | bool | None]] = []
    for card in batch.cards:
        records.extend(card.records)
    return tuple(records)


def _must_keep_separate(identity: KnowledgeIdentityDecision, revision: str | None) -> bool:
    if identity.label == "uncertain":
        return True
    if identity.label == "different_target":
        return True
    if not identity_may_hide(identity):
        return True
    if must_surface_revision(revision):
        return True
    return False


def _equivalence_for(identity: KnowledgeIdentityDecision) -> str:
    if identity.label == "same_target":
        return "equivalent"
    if identity.label == "uncertain":
        return "uncertain"
    return "not_equivalent"


def _separate_identity(identity: KnowledgeIdentityDecision) -> KnowledgeIdentityDecision:
    """Identity used when a later source was kept separate and must not hide."""
    label = "uncertain" if identity.label == "uncertain" else "different_target"
    return KnowledgeIdentityDecision(
        label,
        "kept separate from a prior source; not a hideable duplicate",
        "low" if label == "uncertain" else "high",
        identity.version,
        identity.left_identity_id,
        identity.right_identity_id,
        None,
    )


def _self_identity(candidate: SourceCandidate) -> KnowledgeIdentityDecision:
    fingerprint = fingerprint_claim(
        value=candidate.value,
        detail=candidate.detail,
        slot=candidate.slot,
    )
    return KnowledgeIdentityDecision(
        "same_target",
        "candidate is its own knowledge target",
        "high",
        KNOWLEDGE_IDENTITY_VERSION,
        fingerprint.identity_id,
        fingerprint.identity_id,
        fingerprint.identity_id,
    )


def _sorted(candidates: Sequence[SourceCandidate]) -> tuple[SourceCandidate, ...]:
    return tuple(sorted(candidates, key=lambda item: (item.published_at, item.candidate_id)))


class _Group:
    def __init__(
        self,
        canonical: SourceCandidate,
        identity: KnowledgeIdentityDecision,
        guard: SuppressionDecision,
        revision: str | None,
    ) -> None:
        self.canonical = canonical
        self.identity = identity
        self.guard = guard
        self.revision = revision
        self.members: list[SourceCandidate] = [canonical]
        self.additional: list[AdditionalSource] = []
        self.hidden_ids: list[str] = []
        self.records: list[dict[str, str | bool | None]] = [
            _record(
                candidate=canonical,
                role="hidden" if guard.may_hide else "displayed",
                identity=identity,
                guard=guard,
                revision=revision,
                extra="canonical card after conservative hide guard",
            )
        ]

    @classmethod
    def open(
        cls,
        candidate: SourceCandidate,
        identity: KnowledgeIdentityDecision,
        guard: SuppressionDecision,
        revision: str | None,
    ) -> _Group:
        return cls(candidate, identity, guard, revision)

    def attach(
        self,
        candidate: SourceCandidate,
        identity: KnowledgeIdentityDecision,
        guard: SuppressionDecision,
        revision: str | None,
    ) -> None:
        role = additional_source_role(self.canonical, candidate)
        if role == "independent_confirmation" and normalize_revision(revision) == "NON_NOVEL":
            display_role: AdditionalSourceRole = "independent_confirmation"
        elif role == "syndication":
            display_role = "syndication"
        else:
            display_role = "restatement"
        self.members.append(candidate)
        self.additional.append(
            AdditionalSource(
                candidate_id=candidate.candidate_id,
                source_id=candidate.source_id,
                publisher=candidate.publisher,
                kind=candidate.kind,
                title=candidate.title,
                url=candidate.url,
                published_at=candidate.published_at,
                retrieved_at=candidate.retrieved_at,
                evidence=candidate.evidence,
                dependence_key=candidate.dependence(),
                role=display_role,
                identity_id=identity.shared_identity_id,
                reason=(
                    f"{POLICY_VERSION} attached {display_role} after {guard.version}; "
                    f"guard_action={guard.action} may_hide={str(guard.may_hide).lower()}"
                ),
            )
        )
        self.records.append(
            _record(
                candidate=candidate,
                role="additional_source",
                identity=identity,
                guard=guard,
                revision=revision,
                extra=display_role,
            )
        )

    def hide(
        self,
        candidate: SourceCandidate,
        identity: KnowledgeIdentityDecision,
        guard: SuppressionDecision,
        revision: str | None,
    ) -> None:
        if not guard.may_hide:
            self.attach(candidate, identity, guard, revision)
            return
        self.members.append(candidate)
        self.hidden_ids.append(candidate.candidate_id)
        self.records.append(
            _record(
                candidate=candidate,
                role="hidden",
                identity=identity,
                guard=guard,
                revision=revision,
                extra="hide allowed only by conservative guard",
            )
        )

    def to_card(self) -> ProjectedCard:
        action: VisibilityAction = self.guard.action
        may_hide = self.guard.may_hide
        if action == "hide" and not may_hide:
            action = "show"
        return ProjectedCard(
            displayed_id=self.canonical.candidate_id,
            action=action,
            may_hide=may_hide,
            reason=self.guard.reason,
            version=POLICY_VERSION,
            knowledge_id=self.identity.shared_identity_id,
            additional_sources=tuple(self.additional),
            hidden_ids=tuple(self.hidden_ids),
            independent_evidence_count=independent_evidence_count(self.members),
            guard=self.guard,
            records=tuple(self.records),
        )


def _record(
    *,
    candidate: SourceCandidate,
    role: CandidateRole,
    identity: KnowledgeIdentityDecision,
    guard: SuppressionDecision,
    revision: str | None,
    extra: str,
) -> dict[str, str | bool | None]:
    return {
        "candidate_id": candidate.candidate_id,
        "role": role,
        "reason": extra,
        "version": POLICY_VERSION,
        "guard_version": guard.version,
        "guard_action": guard.action,
        "guard_may_hide": guard.may_hide,
        "guard_reason": guard.reason,
        "identity_label": identity.label,
        "identity_confidence": identity.confidence,
        "identity_version": identity.version,
        "revision_class": revision,
        "dependence_key": candidate.dependence(),
        "knowledge_state": candidate.knowledge_state,
        "knowledge_confidence": candidate.knowledge_confidence,
    }


__all__ = (
    "GUARD_POLICY_VERSION",
    "POLICY_VERSION",
    "AdditionalSource",
    "ProjectedCard",
    "ProjectionBatch",
    "SourceCandidate",
    "additional_source_role",
    "decide_guard",
    "independent_evidence_count",
    "must_surface_revision",
    "normalize_revision",
    "project_candidates",
    "record_projection",
    "resolve_identity",
    "resolve_revision",
)
