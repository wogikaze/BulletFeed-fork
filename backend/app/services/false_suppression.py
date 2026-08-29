"""Conservative false-suppression guard (Known-05 / false-suppression-v1).

Hiding an important fact the user does not know is worse than showing a
duplicate. This guard is the only place that may emit hide.

Uncertain knownness may show or demote. It must never hide.
Low-confidence knownness cannot suppress high-value unknown information.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from app.services.knowledge_evidence import (
    CONFIDENCE_HIGH,
    HIGH_VALUE_IMPORTANCE,
    STATE_KNOWN,
    STATE_PROBABLY_KNOWN,
    STATE_UNKNOWN,
    VisibilityAction,
)
from app.services.knowledge_identity import KnowledgeIdentityDecision, identity_may_hide

POLICY_VERSION: Final = "false-suppression-v1"
MIN_HIDE_CONFIDENCE: Final = CONFIDENCE_HIGH

CROSSING_REVISIONS: Final[frozenset[str]] = frozenset({"CORRECTION", "UNRESOLVED_CONTRADICTION"})
UNCERTAIN_LABELS: Final[frozenset[str]] = frozenset({"uncertain"})
DIFFERENT_LABELS: Final[frozenset[str]] = frozenset({"different_target", "not_equivalent", "not_same_target"})
SAME_LABELS: Final[frozenset[str]] = frozenset({"same_target", "equivalent"})

CONFIDENCE_ORDER: Final[dict[str, int]] = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

SuppressionReason = str
NoveltyLabel = Literal["new", "already_knew"]


@dataclass(frozen=True)
class SuppressionInputs:
    knowledge_state: str
    knowledge_confidence: str
    identity_label: str | None = None
    identity_confidence: str | None = None
    equivalence_label: str | None = None
    revision_class: str | None = None
    importance_level: str | None = None
    stale_exposure: bool = False


@dataclass(frozen=True)
class SuppressionDecision:
    """Audit record for one candidate. Replay is decide_suppression(inputs)."""

    action: VisibilityAction
    may_hide: bool
    reason: str
    version: str
    knowledge_state: str
    knowledge_confidence: str
    identity_label: str | None
    identity_confidence: str | None
    equivalence_label: str | None
    revision_class: str | None
    importance_level: str | None
    stale_exposure: bool

    def as_record(self) -> dict[str, str | bool | None]:
        return {
            "action": self.action,
            "may_hide": self.may_hide,
            "reason": self.reason,
            "version": self.version,
            "knowledge_state": self.knowledge_state,
            "knowledge_confidence": self.knowledge_confidence,
            "identity_label": self.identity_label,
            "identity_confidence": self.identity_confidence,
            "equivalence_label": self.equivalence_label,
            "revision_class": self.revision_class,
            "importance_level": self.importance_level,
            "stale_exposure": self.stale_exposure,
        }


def meets_min_hide_confidence(confidence: str | None) -> bool:
    if confidence is None:
        return False
    return CONFIDENCE_ORDER.get(confidence, -1) >= CONFIDENCE_ORDER[MIN_HIDE_CONFIDENCE]


def is_uncertain_knownness(
    *,
    knowledge_state: str,
    knowledge_confidence: str,
    identity_label: str | None = None,
    identity_confidence: str | None = None,
    equivalence_label: str | None = None,
    stale_exposure: bool = False,
) -> bool:
    """True when hide is forbidden because knownness or identity is uncertain."""
    if knowledge_state != STATE_KNOWN:
        return True
    if not meets_min_hide_confidence(knowledge_confidence):
        return True
    if stale_exposure:
        return True
    if identity_label in UNCERTAIN_LABELS or equivalence_label in UNCERTAIN_LABELS:
        return True
    if identity_label == "same_target" and not meets_min_hide_confidence(identity_confidence):
        return True
    return False


def _is_crossing_revision(revision_class: str | None) -> bool:
    return revision_class in CROSSING_REVISIONS


def _is_different_fact(identity_label: str | None, equivalence_label: str | None) -> bool:
    return identity_label in DIFFERENT_LABELS or equivalence_label in DIFFERENT_LABELS


def _safe_action(knowledge_state: str) -> VisibilityAction:
    if knowledge_state == STATE_PROBABLY_KNOWN:
        return "demote"
    return "show"


def decide_suppression(
    *,
    knowledge_state: str,
    knowledge_confidence: str,
    identity_label: str | None = None,
    identity_confidence: str | None = None,
    equivalence_label: str | None = None,
    revision_class: str | None = None,
    importance_level: str | None = None,
    stale_exposure: bool = False,
    identity: KnowledgeIdentityDecision | None = None,
) -> SuppressionDecision:
    """Decide show / demote / hide. Hide is allowed only after every safety check."""
    if identity is not None:
        identity_label = identity.label
        identity_confidence = identity.confidence

    uncertain = is_uncertain_knownness(
        knowledge_state=knowledge_state,
        knowledge_confidence=knowledge_confidence,
        identity_label=identity_label,
        identity_confidence=identity_confidence,
        equivalence_label=equivalence_label,
        stale_exposure=stale_exposure,
    )
    high_value = importance_level in HIGH_VALUE_IMPORTANCE
    unknownish = knowledge_state != STATE_KNOWN or not meets_min_hide_confidence(knowledge_confidence)

    if _is_crossing_revision(revision_class):
        action: VisibilityAction = "show"
        reason = "high-importance correction/conflict crosses knownness suppression"
    elif high_value and unknownish:
        action = "show"
        reason = "low-confidence knownness cannot suppress high-value unknown information"
    elif knowledge_state == STATE_UNKNOWN:
        action = "show"
        reason = "unknown information must surface"
    elif stale_exposure:
        action = _safe_action(knowledge_state)
        reason = "stale exposure is uncertain knownness; show or demote only"
    elif identity_label in UNCERTAIN_LABELS or equivalence_label in UNCERTAIN_LABELS:
        action = _safe_action(knowledge_state)
        reason = "ambiguous semantic equivalence defaults to re-show/deprioritize"
    elif _is_different_fact(identity_label, equivalence_label):
        action = "show"
        reason = "different knowledge target is not a known duplicate"
    elif identity_label == "same_target" and not meets_min_hide_confidence(identity_confidence):
        action = "demote"
        reason = "suppression requires explicit minimum identity confidence"
    elif not meets_min_hide_confidence(knowledge_confidence):
        action = _safe_action(knowledge_state)
        reason = "suppression requires explicit minimum knowledge confidence"
    elif knowledge_state == STATE_PROBABLY_KNOWN:
        action = "demote"
        reason = "probably_known may demote but not hide"
    elif (
        knowledge_state == STATE_KNOWN
        and meets_min_hide_confidence(knowledge_confidence)
        and (identity_label is None or identity_label in SAME_LABELS)
        and (equivalence_label is None or equivalence_label in SAME_LABELS)
        and not uncertain
        and (identity is None or identity_may_hide(identity))
    ):
        action = "hide"
        reason = "confident known same-target meets minimum hide confidence"
    else:
        action = "show"
        reason = "default conservative show"

    hide_allowed = action == "hide"
    if hide_allowed and uncertain:
        action = _safe_action(knowledge_state)
        reason = "uncertain knownness cannot hide"
        hide_allowed = False

    return SuppressionDecision(
        action=action,
        may_hide=hide_allowed,
        reason=reason,
        version=POLICY_VERSION,
        knowledge_state=knowledge_state,
        knowledge_confidence=knowledge_confidence,
        identity_label=identity_label,
        identity_confidence=identity_confidence,
        equivalence_label=equivalence_label,
        revision_class=revision_class,
        importance_level=importance_level,
        stale_exposure=stale_exposure,
    )


def may_hide(
    *,
    state: str,
    confidence: str,
    importance_level: str | None = None,
    identity_label: str | None = None,
    identity_confidence: str | None = None,
    equivalence_label: str | None = None,
    revision_class: str | None = None,
    stale_exposure: bool = False,
    identity: KnowledgeIdentityDecision | None = None,
) -> bool:
    """Hide is forbidden unless every conservative check passes."""
    return decide_suppression(
        knowledge_state=state,
        knowledge_confidence=confidence,
        identity_label=identity_label,
        identity_confidence=identity_confidence,
        equivalence_label=equivalence_label,
        revision_class=revision_class,
        importance_level=importance_level,
        stale_exposure=stale_exposure,
        identity=identity,
    ).may_hide


def presentation_for_candidate(
    *,
    state: str,
    confidence: str,
    importance_level: str | None = None,
    identity_label: str | None = None,
    identity_confidence: str | None = None,
    equivalence_label: str | None = None,
    revision_class: str | None = None,
    stale_exposure: bool = False,
    identity: KnowledgeIdentityDecision | None = None,
) -> VisibilityAction:
    return decide_suppression(
        knowledge_state=state,
        knowledge_confidence=confidence,
        identity_label=identity_label,
        identity_confidence=identity_confidence,
        equivalence_label=equivalence_label,
        revision_class=revision_class,
        importance_level=importance_level,
        stale_exposure=stale_exposure,
        identity=identity,
    ).action


def reconstruct_why_hidden(decision: SuppressionDecision) -> str:
    """Debug/evaluation text that reconstructs why a candidate was hidden or not."""
    identity = decision.identity_label or "unspecified"
    identity_conf = decision.identity_confidence or "unspecified"
    equivalence = decision.equivalence_label or "unspecified"
    revision = decision.revision_class or "unspecified"
    importance = decision.importance_level or "unspecified"
    stale = "stale" if decision.stale_exposure else "fresh"
    return (
        f"{decision.version} action={decision.action} may_hide={str(decision.may_hide).lower()} "
        f"reason={decision.reason}; "
        f"knowledge={decision.knowledge_state}/{decision.knowledge_confidence} "
        f"identity={identity}/{identity_conf} equivalence={equivalence} "
        f"revision={revision} importance={importance} exposure={stale}"
    )


def record_suppression(
    candidate_id: str,
    decision: SuppressionDecision,
) -> dict[str, str | bool | None]:
    """Every suppressed (or evaluated) candidate keeps reason/version."""
    record = decision.as_record()
    record["candidate_id"] = candidate_id
    return record
