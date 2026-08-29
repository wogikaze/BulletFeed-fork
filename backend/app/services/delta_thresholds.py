"""Versioned asymmetric semantic thresholds (Delta-06 / #71).

False merge hides genuinely new information. False split mainly repeats a card.
Calibration therefore treats merge errors as more expensive than split errors
and never maximizes raw accuracy. Defaults in claim_semantics / coreference
stay untouched; this module is the versioned calibrated overlay.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.services.claim_semantics import SemanticEquivalencePolicy
from app.services.event_coreference import CoreferencePolicy
from app.services.knowledge_evidence import VisibilityAction
from app.services.knowledge_identity import KnowledgeIdentityDecision

THRESHOLDS_VERSION = "delta-thresholds-v1"
SELECTION_SPLIT = "pilot"
FALSE_MERGE_COST = 5.0
FALSE_SPLIT_COST = 1.0
UNCERTAIN_COST = 0.25
ABSTAIN_CONFIDENCE = "low"

# Selected on Rec-01-adjacent #66 pilot by min cost. Blind labels are not inputs.
CALIBRATED_EQUIVALENT_OVERLAP = 0.80
CALIBRATED_DIFFERENT_OVERLAP = 0.55
CALIBRATED_SAME_EVENT_OVERLAP = 0.80
CALIBRATED_DIFFERENT_EVENT_OVERLAP = 0.55

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class CalibratedThresholds:
    version: str
    equivalent_overlap: float
    different_overlap: float
    same_event_overlap: float
    different_event_overlap: float
    false_merge_cost: float
    false_split_cost: float
    uncertain_cost: float
    abstain_confidence: str
    selection_split: str

    @property
    def replay_version(self) -> str:
        return (
            f"{self.version}[eq={self.equivalent_overlap:.2f},"
            f"diff={self.different_overlap:.2f},"
            f"same_event={self.same_event_overlap:.2f},"
            f"merge_cost={self.false_merge_cost:g},"
            f"split_cost={self.false_split_cost:g},"
            f"select={self.selection_split}]"
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["replay_version"] = self.replay_version
        return payload

    def equivalence_policy(self) -> SemanticEquivalencePolicy:
        return SemanticEquivalencePolicy(
            equivalent_overlap=self.equivalent_overlap,
            different_overlap=self.different_overlap,
            version=f"{THRESHOLDS_VERSION}-equivalence",
        )

    def coreference_policy(self) -> CoreferencePolicy:
        return CoreferencePolicy(
            same_event_overlap=self.same_event_overlap,
            different_event_overlap=self.different_event_overlap,
            version=f"{THRESHOLDS_VERSION}-coreference",
        )


def calibrated_thresholds() -> CalibratedThresholds:
    return CalibratedThresholds(
        version=THRESHOLDS_VERSION,
        equivalent_overlap=CALIBRATED_EQUIVALENT_OVERLAP,
        different_overlap=CALIBRATED_DIFFERENT_OVERLAP,
        same_event_overlap=CALIBRATED_SAME_EVENT_OVERLAP,
        different_event_overlap=CALIBRATED_DIFFERENT_EVENT_OVERLAP,
        false_merge_cost=FALSE_MERGE_COST,
        false_split_cost=FALSE_SPLIT_COST,
        uncertain_cost=UNCERTAIN_COST,
        abstain_confidence=ABSTAIN_CONFIDENCE,
        selection_split=SELECTION_SPLIT,
    )


def decision_cost(
    *,
    false_merge_count: int,
    false_split_count: int,
    uncertain_count: int,
    thresholds: CalibratedThresholds | None = None,
) -> float:
    policy = thresholds or calibrated_thresholds()
    return (
        false_merge_count * policy.false_merge_cost
        + false_split_count * policy.false_split_cost
        + uncertain_count * policy.uncertain_cost
    )


def should_abstain(confidence: str, *, thresholds: CalibratedThresholds | None = None) -> bool:
    policy = thresholds or calibrated_thresholds()
    order = {"low": 1, "medium": 2, "high": 3}
    return order.get(confidence, 0) <= order.get(policy.abstain_confidence, 1)


def apply_merge_abstention(
    label: str,
    confidence: str,
    *,
    thresholds: CalibratedThresholds | None = None,
) -> tuple[str, bool]:
    """Low-confidence zones become uncertain and must not merge."""
    if should_abstain(confidence, thresholds=thresholds):
        return "uncertain", False
    if label in {"equivalent", "same_event", "same_target"}:
        return label, True
    if label == "uncertain":
        return "uncertain", False
    return label, False


def calibrated_knownness_may_hide(
    decision: KnowledgeIdentityDecision,
    *,
    thresholds: CalibratedThresholds | None = None,
) -> bool:
    """#53: uncertain or low-confidence identity cannot hide."""
    _label, may_merge = apply_merge_abstention(
        decision.label,
        decision.confidence,
        thresholds=thresholds,
    )
    return may_merge and decision.label == "same_target" and decision.confidence == "high"


def calibrated_knownness_visibility(
    decision: KnowledgeIdentityDecision,
    derived_visibility: VisibilityAction,
    *,
    thresholds: CalibratedThresholds | None = None,
) -> VisibilityAction:
    if calibrated_knownness_may_hide(decision, thresholds=thresholds):
        return derived_visibility
    if derived_visibility == "hide":
        if decision.label == "same_target":
            return "demote"
        return "show"
    return derived_visibility if derived_visibility != "hide" else "show"


def replay_metadata(thresholds: CalibratedThresholds | None = None) -> dict[str, Any]:
    policy = thresholds or calibrated_thresholds()
    return {
        "delta_thresholds_version": policy.version,
        "replay_version": policy.replay_version,
        "selection_split": policy.selection_split,
        "false_merge_cost": policy.false_merge_cost,
        "false_split_cost": policy.false_split_cost,
        "equivalent_overlap": policy.equivalent_overlap,
        "different_overlap": policy.different_overlap,
        "same_event_overlap": policy.same_event_overlap,
        "different_event_overlap": policy.different_event_overlap,
    }
