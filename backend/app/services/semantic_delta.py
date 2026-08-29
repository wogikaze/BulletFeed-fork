from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.claim_semantics import canonicalize_text, compare_claim_texts
from app.services.semantic_equivalence import compare_semantic_equivalence

RevisionType = Literal[
    "NEW_FACT",
    "DETAIL",
    "STATE_UPDATE",
    "CORRECTION",
    "UNRESOLVED_CONTRADICTION",
    "NON_NOVEL",
]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class ClaimSnapshot:
    value: str
    detail: str
    valid_at: str


@dataclass(frozen=True)
class DeltaContext:
    explicit_correction: bool = False
    unresolved_source_conflict: bool = False


@dataclass(frozen=True)
class RevisionDecision:
    revision_type: RevisionType
    reason: str
    confidence: Confidence
    version: str = "revision-judge-v1"
    abstained: bool = False


def _with_policy(reason: str, policy_version: str) -> str:
    return f"{reason} [policy={policy_version}]"


def judge_revision(
    prior: ClaimSnapshot | None,
    candidate: ClaimSnapshot,
    *,
    context: DeltaContext | None = None,
) -> RevisionDecision:
    context = context or DeltaContext()
    if prior is None:
        return RevisionDecision("NEW_FACT", "no prior settled claim exists", "high")
    if context.explicit_correction:
        return RevisionDecision("CORRECTION", "source explicitly marks this claim as a correction", "high")
    if context.unresolved_source_conflict:
        return RevisionDecision(
            "UNRESOLVED_CONTRADICTION",
            "source evidence explicitly remains in conflict",
            "high",
        )

    equivalence = compare_semantic_equivalence(
        prior.value,
        prior.detail,
        candidate.value,
        candidate.detail,
    )
    if equivalence.label == "equivalent":
        return RevisionDecision(
            "NON_NOVEL",
            _with_policy(f"semantic restatement: {equivalence.reason}", equivalence.version),
            equivalence.confidence,
        )

    prior_value = canonicalize_text(prior.value)
    candidate_value = canonicalize_text(candidate.value)
    value_decision = compare_claim_texts(prior_value, candidate_value)
    if value_decision.label == "equivalent":
        return RevisionDecision(
            "DETAIL",
            _with_policy(
                f"state/value is unchanged while detail changed: {equivalence.reason}",
                value_decision.version,
            ),
            "high" if value_decision.confidence == "high" else "medium",
        )

    if value_decision.label == "uncertain":
        return RevisionDecision(
            "UNRESOLVED_CONTRADICTION",
            _with_policy(
                "semantic value comparison is uncertain; abstaining from changing settled state",
                value_decision.version,
            ),
            "low",
            abstained=True,
        )
    if candidate.valid_at == prior.valid_at:
        return RevisionDecision(
            "UNRESOLVED_CONTRADICTION",
            _with_policy(
                "incompatible claims have the same valid time; abstaining from supersession",
                value_decision.version,
            ),
            "high",
        )
    if candidate.valid_at > prior.valid_at:
        return RevisionDecision(
            "STATE_UPDATE",
            _with_policy(
                f"claim value changed at a later valid time: {value_decision.reason}",
                value_decision.version,
            ),
            "high",
        )
    return RevisionDecision(
        "NEW_FACT",
        _with_policy(
            "candidate predates the settled prior claim and is retained as historical fact",
            value_decision.version,
        ),
        "medium",
    )


def classify_revision(
    prior: ClaimSnapshot | None,
    candidate: ClaimSnapshot,
    *,
    context: DeltaContext | None = None,
) -> RevisionType:
    return judge_revision(prior, candidate, context=context).revision_type
