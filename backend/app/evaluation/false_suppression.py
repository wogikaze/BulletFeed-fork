"""False-suppression metrics, kept separate from repetition (Known-05)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.services.false_suppression import (
    POLICY_VERSION,
    SuppressionDecision,
    decide_suppression,
)
from app.services.knowledge_evidence import VisibilityAction

DATASET_VERSION = "false-suppression-v0.1"
POLICY_ID = POLICY_VERSION

REQUIRED_FAMILIES: tuple[str, ...] = (
    "uncertain_paraphrase",
    "partial_detail",
    "stale_exposure",
    "correction",
    "conflicting_source",
    "high_importance_unknown",
)

FamilyName = Literal[
    "uncertain_paraphrase",
    "partial_detail",
    "stale_exposure",
    "correction",
    "conflicting_source",
    "high_importance_unknown",
    "confident_known_restatement",
    "low_confidence_known",
]
NoveltyLabel = Literal["new", "already_knew"]


@dataclass(frozen=True)
class FalseSuppressionCase:
    case_id: str
    family: str
    knowledge_state: str
    knowledge_confidence: str
    identity_label: str | None
    identity_confidence: str | None
    equivalence_label: str | None
    revision_class: str | None
    importance_level: str | None
    stale_exposure: bool
    gold_novelty: NoveltyLabel
    should_surface: bool
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class FalseSuppressionReport:
    dataset_version: str
    policy_version: str
    case_count: int
    unknown_count: int
    known_duplicate_count: int
    unknown_but_hidden_count: int
    repeated_count: int
    false_suppression_rate: float
    repetition_rate: float
    hidden_ids: tuple[str, ...]
    repeated_ids: tuple[str, ...]


@dataclass(frozen=True)
class FalseSuppressionThresholds:
    false_suppression_rate: float = 0.0
    material_false_suppression_increase: float = 0.0


DEFAULT_FALSE_SUPPRESSION_GATE = FalseSuppressionThresholds()


def load_false_suppression_gold(path: Path) -> tuple[FalseSuppressionCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("dataset_id") != "bulletfeed-false-suppression-v0.1":
        raise ValueError("unexpected false-suppression dataset_id")
    if payload.get("version") != POLICY_VERSION:
        raise ValueError("unexpected false-suppression version")
    cases = tuple(_case_from_payload(item) for item in payload["cases"])
    _validate_corpus(cases)
    return cases


def decide_case(case: FalseSuppressionCase) -> SuppressionDecision:
    return decide_suppression(
        knowledge_state=case.knowledge_state,
        knowledge_confidence=case.knowledge_confidence,
        identity_label=case.identity_label,
        identity_confidence=case.identity_confidence,
        equivalence_label=case.equivalence_label,
        revision_class=case.revision_class,
        importance_level=case.importance_level,
        stale_exposure=case.stale_exposure,
    )


def policy_prediction(case: FalseSuppressionCase) -> VisibilityAction:
    return decide_case(case).action


def hide_non_unknown_prediction(case: FalseSuppressionCase) -> VisibilityAction:
    """Aggressive baseline: hide anything not strictly unknown.

    Improves repetition by treating uncertain/probably_known as hide.
    That is the regression this metric must reject.
    """
    if case.knowledge_state == "unknown":
        return "show"
    return "hide"


def evaluate_false_suppression(
    cases: Sequence[FalseSuppressionCase],
    predictions: Mapping[str, str],
    *,
    policy_version: str = POLICY_VERSION,
) -> FalseSuppressionReport:
    unknown = [case for case in cases if case.gold_novelty == "new"]
    known_duplicates = [
        case
        for case in cases
        if case.gold_novelty == "already_knew" and not case.should_surface
    ]
    unknown_hidden = [
        case for case in unknown if predictions.get(case.case_id) == "hide"
    ]
    repeated = [
        case for case in known_duplicates if predictions.get(case.case_id) != "hide"
    ]
    return FalseSuppressionReport(
        dataset_version=DATASET_VERSION,
        policy_version=policy_version,
        case_count=len(cases),
        unknown_count=len(unknown),
        known_duplicate_count=len(known_duplicates),
        unknown_but_hidden_count=len(unknown_hidden),
        repeated_count=len(repeated),
        false_suppression_rate=_ratio(len(unknown_hidden), len(unknown)),
        repetition_rate=_ratio(len(repeated), len(known_duplicates), empty=0.0),
        hidden_ids=tuple(case.case_id for case in unknown_hidden),
        repeated_ids=tuple(case.case_id for case in repeated),
    )


def evaluate_policy(
    cases: Sequence[FalseSuppressionCase],
    predict: Callable[[FalseSuppressionCase], str] = policy_prediction,
) -> FalseSuppressionReport:
    return evaluate_false_suppression(
        cases,
        {case.case_id: predict(case) for case in cases},
    )


def false_suppression_release_violations(
    report: FalseSuppressionReport,
    thresholds: FalseSuppressionThresholds = DEFAULT_FALSE_SUPPRESSION_GATE,
) -> tuple[str, ...]:
    violations: list[str] = []
    if report.false_suppression_rate > thresholds.false_suppression_rate:
        violations.append(
            "false_suppression_rate "
            f"{report.false_suppression_rate:.3f} > {thresholds.false_suppression_rate:.3f}"
        )
    return tuple(violations)


def repetition_regression_violations(
    current: FalseSuppressionReport,
    previous: FalseSuppressionReport,
    thresholds: FalseSuppressionThresholds = DEFAULT_FALSE_SUPPRESSION_GATE,
) -> tuple[str, ...]:
    """A release cannot improve repetition by raising unknown-but-hidden."""
    repetition_improved = current.repetition_rate < previous.repetition_rate
    increase = current.false_suppression_rate - previous.false_suppression_rate
    if repetition_improved and increase > thresholds.material_false_suppression_increase:
        return (
            "repetition_rate improved "
            f"{previous.repetition_rate:.3f} -> {current.repetition_rate:.3f} "
            "by increasing unknown-but-hidden "
            f"{previous.false_suppression_rate:.3f} -> {current.false_suppression_rate:.3f}",
        )
    return ()


def require_false_suppression_gate(
    report: FalseSuppressionReport,
    thresholds: FalseSuppressionThresholds = DEFAULT_FALSE_SUPPRESSION_GATE,
) -> None:
    violations = false_suppression_release_violations(report, thresholds)
    if violations:
        raise AssertionError(
            "false-suppression release gate failed: " + "; ".join(violations)
        )


def require_no_repetition_false_suppression_tradeoff(
    current: FalseSuppressionReport,
    previous: FalseSuppressionReport,
    thresholds: FalseSuppressionThresholds = DEFAULT_FALSE_SUPPRESSION_GATE,
) -> None:
    violations = repetition_regression_violations(current, previous, thresholds)
    if violations:
        raise AssertionError(
            "false-suppression release gate failed: " + "; ".join(violations)
        )


def _case_from_payload(item: Mapping[str, Any]) -> FalseSuppressionCase:
    allowed = tuple(item.get("allowed_actions") or ("show", "demote", "hide"))
    forbidden = tuple(item.get("forbidden_actions") or ())
    return FalseSuppressionCase(
        case_id=str(item["id"]),
        family=str(item["family"]),
        knowledge_state=str(item["knowledge_state"]),
        knowledge_confidence=str(item["knowledge_confidence"]),
        identity_label=item.get("identity_label"),
        identity_confidence=item.get("identity_confidence"),
        equivalence_label=item.get("equivalence_label"),
        revision_class=item.get("revision_class"),
        importance_level=item.get("importance_level"),
        stale_exposure=bool(item.get("stale_exposure", False)),
        gold_novelty=item["gold_novelty"],
        should_surface=bool(item["should_surface"]),
        allowed_actions=allowed,
        forbidden_actions=forbidden,
        rationale=str(item["rationale"]),
    )


def _validate_corpus(cases: Sequence[FalseSuppressionCase]) -> None:
    if not cases:
        raise ValueError("false-suppression corpus has no cases")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate false-suppression case ids")
    families = {case.family for case in cases}
    missing = set(REQUIRED_FAMILIES) - families
    if missing:
        raise ValueError(f"corpus missing required families: {sorted(missing)}")
    if not any(case.gold_novelty == "new" for case in cases):
        raise ValueError("corpus needs gold-new cases for false-suppression rate")
    if not any(
        case.gold_novelty == "already_knew" and not case.should_surface for case in cases
    ):
        raise ValueError("corpus needs known-duplicate cases for repetition rate")


def _ratio(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    if denominator == 0:
        return empty
    return numerator / denominator


# presentation_for_candidate is the policy used by evaluate_policy.
__all__ = (
    "DATASET_VERSION",
    "DEFAULT_FALSE_SUPPRESSION_GATE",
    "FalseSuppressionCase",
    "FalseSuppressionReport",
    "FalseSuppressionThresholds",
    "POLICY_ID",
    "REQUIRED_FAMILIES",
    "decide_case",
    "evaluate_false_suppression",
    "evaluate_policy",
    "false_suppression_release_violations",
    "hide_non_unknown_prediction",
    "load_false_suppression_gold",
    "policy_prediction",
    "repetition_regression_violations",
    "require_false_suppression_gate",
    "require_no_repetition_false_suppression_tradeoff",
)
