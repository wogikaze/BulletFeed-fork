"""Calibrate equivalence/coreference thresholds on #66 gold (Delta-06).

Selection uses pilot/dev only and minimizes an asymmetric cost. Blind labels
are evaluation-only. Gold judgments are never rewritten.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from app.evaluation.coreference import compare_delta_adversarial_case
from app.evaluation.delta_adversarial_gold import (
    DeltaAdversarialCase,
    DeltaAdversarialCorpus,
    DeltaAdversarialPrediction,
    evaluate_delta_adversarial,
    load_delta_adversarial_gold,
)
from app.evaluation.semantic_quality import ConfidenceBucket, confidence_buckets
from app.services.claim_semantics import DEFAULT_EQUIVALENCE_POLICY, compare_claims
from app.services.delta_thresholds import (
    FALSE_MERGE_COST,
    FALSE_SPLIT_COST,
    SELECTION_SPLIT,
    THRESHOLDS_VERSION,
    CalibratedThresholds,
    apply_merge_abstention,
    calibrated_thresholds,
    decision_cost,
    replay_metadata,
)
from app.services.event_coreference import DEFAULT_COREFERENCE_POLICY

BENCHMARK_VERSION = "delta-calibration-v0.1"
EQUIVALENCE_GRID = (0.80, 0.85, 0.90, 0.95, 0.99)
DIFFERENT_GRID = (0.25, 0.35, 0.45, 0.55)

# Blind release floors: merge is stricter than split. Accuracy is not a floor.
FALSE_MERGE_RATE_FLOOR = 0.15
FALSE_SPLIT_RATE_FLOOR = 0.85


@dataclass(frozen=True)
class CandidateScore:
    equivalent_overlap: float
    different_overlap: float
    false_merge_count: int
    false_split_count: int
    uncertain_count: int
    accuracy: float
    cost: float
    pair_count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilyCalibration:
    family: str
    pair_count: int
    false_merge_count: int
    false_split_count: int
    uncertain_count: int
    reliability: tuple[ConfidenceBucket, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "pair_count": self.pair_count,
            "false_merge_count": self.false_merge_count,
            "false_split_count": self.false_split_count,
            "uncertain_count": self.uncertain_count,
            "reliability": [asdict(row) for row in self.reliability],
        }


@dataclass(frozen=True)
class CalibrationReport:
    benchmark_version: str
    dataset_version: str
    split: str
    thresholds: CalibratedThresholds
    selected: CandidateScore
    accuracy_maximizer: CandidateScore
    selected_by: Literal["asymmetric_cost"]
    labels_rewritten: bool
    false_merge_count: int
    false_split_count: int
    false_merge_rate: float
    false_split_rate: float
    predicted_uncertain_count: int
    families: tuple[FamilyCalibration, ...]
    replay: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "benchmark_version": self.benchmark_version,
            "dataset_version": self.dataset_version,
            "split": self.split,
            "thresholds": self.thresholds.as_dict(),
            "selected": self.selected.as_dict(),
            "accuracy_maximizer": self.accuracy_maximizer.as_dict(),
            "selected_by": self.selected_by,
            "labels_rewritten": self.labels_rewritten,
            "false_merge_count": self.false_merge_count,
            "false_split_count": self.false_split_count,
            "false_merge_rate": self.false_merge_rate,
            "false_split_rate": self.false_split_rate,
            "predicted_uncertain_count": self.predicted_uncertain_count,
            "families": [row.as_dict() for row in self.families],
            "replay": self.replay,
        }


def load_calibration_gold(corpus_dir: Path) -> DeltaAdversarialCorpus:
    return load_delta_adversarial_gold(corpus_dir)


def candidate_grid() -> tuple[tuple[float, float], ...]:
    pairs = [
        (equivalent, different)
        for equivalent in EQUIVALENCE_GRID
        for different in DIFFERENT_GRID
        if different < equivalent
    ]
    return tuple(pairs)


def predict_case(
    case: DeltaAdversarialCase,
    thresholds: CalibratedThresholds,
) -> tuple[DeltaAdversarialPrediction, str, str, bool]:
    """Return (delta prediction, equivalence label after abstention, confidence, abstained)."""
    equivalence = compare_claims(
        case.prior.value,
        case.prior.detail,
        case.candidate.value,
        case.candidate.detail,
        policy=thresholds.equivalence_policy(),
    )
    eq_label, may_merge = apply_merge_abstention(
        equivalence.label,
        equivalence.confidence,
        thresholds=thresholds,
    )
    coref = compare_delta_adversarial_case(case, policy=thresholds.coreference_policy())
    coref_label, coref_merge = apply_merge_abstention(
        coref.label,
        coref.confidence,
        thresholds=thresholds,
    )
    same_event = bool(may_merge and coref_merge)
    predicted_eq = "equivalent" if same_event and eq_label == "equivalent" else "not_equivalent"
    if eq_label == "uncertain":
        predicted_eq = "not_equivalent"
    prediction = DeltaAdversarialPrediction(
        case_id=case.case_id,
        equivalence=predicted_eq,
        revision_class="NON_NOVEL" if same_event else "NEW_FACT",
        same_event=same_event,
    )
    abstained = eq_label == "uncertain" or coref_label == "uncertain"
    return prediction, eq_label, equivalence.confidence, abstained


def score_thresholds(
    corpus: DeltaAdversarialCorpus,
    thresholds: CalibratedThresholds,
    *,
    split: str | None = None,
) -> CandidateScore:
    scoped = corpus.for_split(split) if split is not None else corpus
    predicted: dict[str, DeltaAdversarialPrediction] = {}
    uncertain = 0
    correct = 0
    for case in scoped.cases:
        prediction, eq_label, _confidence, abstained = predict_case(case, thresholds)
        predicted[case.case_id] = prediction
        if abstained or eq_label == "uncertain":
            uncertain += 1
        gold_same = case.same_gold_event
        if prediction.same_event == gold_same:
            correct += 1
    report = evaluate_delta_adversarial(scoped, predicted, split=split)
    return CandidateScore(
        equivalent_overlap=thresholds.equivalent_overlap,
        different_overlap=thresholds.different_overlap,
        false_merge_count=report.false_merge_count,
        false_split_count=report.false_split_count,
        uncertain_count=uncertain,
        accuracy=correct / len(scoped.cases) if scoped.cases else 0.0,
        cost=decision_cost(
            false_merge_count=report.false_merge_count,
            false_split_count=report.false_split_count,
            uncertain_count=uncertain,
            thresholds=thresholds,
        ),
        pair_count=len(scoped.cases),
    )


def select_thresholds(
    corpus: DeltaAdversarialCorpus,
) -> tuple[CalibratedThresholds, CandidateScore, CandidateScore]:
    """Pilot-only selection. Minimizes asymmetric cost, not accuracy."""
    pilot = corpus.for_split(SELECTION_SPLIT)
    scored: list[CandidateScore] = []
    for equivalent, different in candidate_grid():
        candidate = CalibratedThresholds(
            version=THRESHOLDS_VERSION,
            equivalent_overlap=equivalent,
            different_overlap=different,
            same_event_overlap=equivalent,
            different_event_overlap=different,
            false_merge_cost=FALSE_MERGE_COST,
            false_split_cost=FALSE_SPLIT_COST,
            uncertain_cost=calibrated_thresholds().uncertain_cost,
            abstain_confidence=calibrated_thresholds().abstain_confidence,
            selection_split=SELECTION_SPLIT,
        )
        scored.append(score_thresholds(pilot, candidate, split=SELECTION_SPLIT))
    if not scored:
        raise ValueError("calibration grid is empty")
    by_cost = sorted(
        scored,
        key=lambda row: (row.cost, row.false_merge_count, -row.equivalent_overlap),
    )
    by_accuracy = sorted(
        scored,
        key=lambda row: (-row.accuracy, row.false_merge_count, row.cost),
    )
    chosen = by_cost[0]
    thresholds = CalibratedThresholds(
        version=THRESHOLDS_VERSION,
        equivalent_overlap=chosen.equivalent_overlap,
        different_overlap=chosen.different_overlap,
        same_event_overlap=chosen.equivalent_overlap,
        different_event_overlap=chosen.different_overlap,
        false_merge_cost=FALSE_MERGE_COST,
        false_split_cost=FALSE_SPLIT_COST,
        uncertain_cost=calibrated_thresholds().uncertain_cost,
        abstain_confidence=calibrated_thresholds().abstain_confidence,
        selection_split=SELECTION_SPLIT,
    )
    return thresholds, chosen, by_accuracy[0]


def evaluate_calibration(
    corpus: DeltaAdversarialCorpus,
    *,
    split: Literal["pilot", "blind"],
    thresholds: CalibratedThresholds | None = None,
    selected: CandidateScore | None = None,
    accuracy_maximizer: CandidateScore | None = None,
) -> CalibrationReport:
    policy = thresholds or calibrated_thresholds()
    if selected is None or accuracy_maximizer is None:
        selected_policy, selected, accuracy_maximizer = select_thresholds(corpus)
        if thresholds is None:
            policy = selected_policy
    scoped = corpus.for_split(split)
    predictions: dict[str, DeltaAdversarialPrediction] = {}
    eq_samples: list[tuple[str, bool, bool]] = []
    coref_samples: list[tuple[str, bool, bool]] = []
    uncertain = 0
    for case in scoped.cases:
        prediction, eq_label, confidence, abstained = predict_case(case, policy)
        predictions[case.case_id] = prediction
        if abstained:
            uncertain += 1
        eq_correct = (eq_label == "equivalent") == (case.equivalence == "equivalent")
        coref_correct = prediction.same_event == case.same_gold_event
        eq_samples.append((confidence, eq_correct, abstained))
        coref_samples.append((confidence, coref_correct, abstained))
    delta = evaluate_delta_adversarial(scoped, predictions, split=split)
    pair_count = len(scoped.cases)
    families = (
        FamilyCalibration(
            "equivalence",
            pair_count,
            delta.false_merge_count,
            delta.false_split_count,
            uncertain,
            confidence_buckets(tuple(eq_samples)),
        ),
        FamilyCalibration(
            "coreference",
            pair_count,
            delta.false_merge_count,
            delta.false_split_count,
            uncertain,
            confidence_buckets(tuple(coref_samples)),
        ),
    )
    return CalibrationReport(
        benchmark_version=BENCHMARK_VERSION,
        dataset_version=scoped.dataset_version,
        split=split,
        thresholds=policy,
        selected=selected,
        accuracy_maximizer=accuracy_maximizer,
        selected_by="asymmetric_cost",
        labels_rewritten=False,
        false_merge_count=delta.false_merge_count,
        false_split_count=delta.false_split_count,
        false_merge_rate=delta.false_merge_count / pair_count if pair_count else 0.0,
        false_split_rate=delta.false_split_count / pair_count if pair_count else 0.0,
        predicted_uncertain_count=uncertain,
        families=families,
        replay=replay_metadata(policy),
    )


def calibration_release_violations(report: CalibrationReport) -> tuple[str, ...]:
    violations: list[str] = []
    if report.false_merge_rate > FALSE_MERGE_RATE_FLOOR:
        violations.append(
            f"false_merge_rate {report.false_merge_rate:.3f} > {FALSE_MERGE_RATE_FLOOR:.3f}"
        )
    if report.false_split_rate > FALSE_SPLIT_RATE_FLOOR:
        violations.append(
            f"false_split_rate {report.false_split_rate:.3f} > {FALSE_SPLIT_RATE_FLOOR:.3f}"
        )
    if FALSE_MERGE_RATE_FLOOR >= FALSE_SPLIT_RATE_FLOOR:
        violations.append("false merge floor must be stricter than false split floor")
    if report.selected_by != "asymmetric_cost":
        violations.append("thresholds must be selected by asymmetric cost, not accuracy")
    if report.labels_rewritten:
        violations.append("gold labels must not be rewritten")
    if report.thresholds.false_merge_cost <= report.thresholds.false_split_cost:
        violations.append("false merge cost must exceed false split cost")
    return tuple(violations)


def require_calibration_release_gate(report: CalibrationReport) -> None:
    violations = calibration_release_violations(report)
    if violations:
        raise AssertionError("delta calibration release gate failed: " + "; ".join(violations))


def write_report(report: CalibrationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("baseline report must be an object")
    return payload


def default_algorithm_score(corpus: DeltaAdversarialCorpus, *, split: str) -> CandidateScore:
    """Diagnostic only. Default constants are not retuned against gold."""
    thresholds = CalibratedThresholds(
        version="uncalibrated-default",
        equivalent_overlap=DEFAULT_EQUIVALENCE_POLICY.equivalent_overlap,
        different_overlap=DEFAULT_EQUIVALENCE_POLICY.different_overlap,
        same_event_overlap=DEFAULT_COREFERENCE_POLICY.same_event_overlap,
        different_event_overlap=DEFAULT_COREFERENCE_POLICY.different_event_overlap,
        false_merge_cost=FALSE_MERGE_COST,
        false_split_cost=FALSE_SPLIT_COST,
        uncertain_cost=calibrated_thresholds().uncertain_cost,
        abstain_confidence=calibrated_thresholds().abstain_confidence,
        selection_split=SELECTION_SPLIT,
    )
    return score_thresholds(corpus, thresholds, split=split)


def persist_selected_thresholds(thresholds: CalibratedThresholds, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(thresholds.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
