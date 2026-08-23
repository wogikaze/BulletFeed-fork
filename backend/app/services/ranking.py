from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ImportanceLevel = Literal["critical", "high", "medium", "low"]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class ImportanceDecision:
    level: ImportanceLevel
    reason: str
    confidence: Confidence


def evaluate_importance(*, source_type: str, delta_type: str) -> ImportanceDecision:
    """Deterministic v0 importance, deliberately independent of novelty/relation."""
    if delta_type == "correction":
        return ImportanceDecision(
            level="high",
            reason="A correction can invalidate information that was previously delivered.",
            confidence="high",
        )
    if delta_type == "unresolved_contradiction":
        return ImportanceDecision(
            level="high",
            reason="Authoritative evidence remains in unresolved conflict.",
            confidence="high",
        )
    if source_type in {"osv", "github_advisory"}:
        return ImportanceDecision(
            level="high",
            reason="Security advisory changes can require dependency or remediation action.",
            confidence="high",
        )
    if delta_type == "state_update":
        return ImportanceDecision(
            level="medium",
            reason="A tracked event changed state.",
            confidence="high",
        )
    if source_type == "github_release":
        return ImportanceDecision(
            level="medium",
            reason="A tracked software release changed.",
            confidence="high",
        )
    return ImportanceDecision(
        level="medium",
        reason="A tracked authoritative source contains a meaningful new delta.",
        confidence="medium",
    )
