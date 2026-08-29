"""Asymmetric product-value release floors (Eval-02 / #73).

Catastrophic metrics are hard gates and cannot be offset by a higher
aggregate score. Floor changes require a new version and reason.
Blind labels are not loaded by this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.e2e_unknown_recall import (
    evaluate_e2e_unknown_recall,
    load_e2e_cases,
)
from app.evaluation.knownness_gold import (
    KnownnessPrediction,
    evaluate_knownness,
    load_knownness_gold_for_production_scoring,
    replay_derived_knowledge,
)
from app.evaluation.source_coverage import evaluate_source_coverage, load_source_coverage_gold
from app.services.knowledge_evidence import STATE_KNOWN

GATE_FAMILY = "product-release-floors"
HARD_METRICS = ("unknown_but_hidden", "false_merge_misses")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CohortFloors(_Strict):
    important_unknown_recall: float = 0.6


class ProductReleaseFloors(_Strict):
    version: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    unknown_but_hidden: int = 0
    false_merge_misses: int = 0
    important_unknown_recall: float = 0.7
    known_but_reshown_rate: float = 0.35
    unknown_but_hidden_rate: float = 0.0
    discovery_recall: float = 0.7
    authoritative_source_precision: float = 0.7
    cold_start: CohortFloors = Field(default_factory=CohortFloors)
    history_rich: CohortFloors = Field(default_factory=CohortFloors)


@dataclass(frozen=True)
class GateFinding:
    metric: str
    observed: float
    floor: float
    hard: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "observed": self.observed,
            "floor": self.floor,
            "hard": self.hard,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ProductReleaseReport:
    floors_version: str
    reason: str
    findings: tuple[GateFinding, ...]
    hard_failures: tuple[str, ...]
    observations: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "floors_version": self.floors_version,
            "reason": self.reason,
            "hard_failures": list(self.hard_failures),
            "observations": self.observations,
            "findings": [item.as_dict() for item in self.findings],
        }


def load_product_release_floors(path: Path) -> ProductReleaseFloors:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ProductReleaseFloors.model_validate(payload)


def knownness_prediction_from_replay(case) -> KnownnessPrediction:
    derived = replay_derived_knowledge(case)
    known = derived.state == STATE_KNOWN
    return KnownnessPrediction(
        case_id=case.case_id,
        predicted_known=known,
        predicted_surface=derived.visibility != "hide",
        predicted_novel_fact=not known,
        predicted_correction=case.candidate.relation_to_prior == "correction",
    )


def evaluate_product_release_gate(
    *,
    floors: ProductReleaseFloors,
    e2e_cases_path: Path,
    knownness_dir: Path,
    coverage_dir: Path,
) -> ProductReleaseReport:
    e2e = evaluate_e2e_unknown_recall(load_e2e_cases(e2e_cases_path))
    knownness_corpus = load_knownness_gold_for_production_scoring(knownness_dir)
    knownness = evaluate_knownness(
        knownness_corpus,
        {case.case_id: knownness_prediction_from_replay(case) for case in knownness_corpus.cases},
        split="pilot",
    )
    coverage = evaluate_source_coverage(load_source_coverage_gold(coverage_dir), split="pilot")
    observations = {
        "unknown_but_hidden": float(e2e.overall.unknown_but_hidden),
        "false_merge_misses": float(e2e.overall.false_merge_misses),
        "important_unknown_recall": e2e.overall.important_unknown_recall,
        "known_but_reshown_rate": knownness.exclude_ambiguous.known_but_reshown_rate,
        "unknown_but_hidden_rate": knownness.exclude_ambiguous.unknown_but_hidden_rate,
        "discovery_recall": coverage.discovery_recall,
        "authoritative_source_precision": coverage.authoritative_source_precision,
        "cold_start_important_unknown_recall": e2e.by_cohort["cold_start"].important_unknown_recall,
        "history_rich_important_unknown_recall": e2e.by_cohort["history_rich"].important_unknown_recall,
    }
    findings: list[GateFinding] = []

    def _max(name: str, observed: float, floor: float, *, hard: bool) -> None:
        if observed > floor:
            findings.append(
                GateFinding(
                    metric=name,
                    observed=observed,
                    floor=floor,
                    hard=hard,
                    detail=f"{name} {observed:.3f} > {floor:.3f}",
                )
            )

    def _min(name: str, observed: float, floor: float, *, hard: bool) -> None:
        if observed < floor:
            findings.append(
                GateFinding(
                    metric=name,
                    observed=observed,
                    floor=floor,
                    hard=hard,
                    detail=f"{name} {observed:.3f} < {floor:.3f}",
                )
            )

    _max("unknown_but_hidden", observations["unknown_but_hidden"], floors.unknown_but_hidden, hard=True)
    _max("false_merge_misses", observations["false_merge_misses"], floors.false_merge_misses, hard=True)
    _max(
        "unknown_but_hidden_rate",
        observations["unknown_but_hidden_rate"],
        floors.unknown_but_hidden_rate,
        hard=True,
    )
    _min(
        "important_unknown_recall",
        observations["important_unknown_recall"],
        floors.important_unknown_recall,
        hard=False,
    )
    _max(
        "known_but_reshown_rate",
        observations["known_but_reshown_rate"],
        floors.known_but_reshown_rate,
        hard=False,
    )
    _min("discovery_recall", observations["discovery_recall"], floors.discovery_recall, hard=False)
    _min(
        "authoritative_source_precision",
        observations["authoritative_source_precision"],
        floors.authoritative_source_precision,
        hard=False,
    )
    _min(
        "cold_start_important_unknown_recall",
        observations["cold_start_important_unknown_recall"],
        floors.cold_start.important_unknown_recall,
        hard=False,
    )
    _min(
        "history_rich_important_unknown_recall",
        observations["history_rich_important_unknown_recall"],
        floors.history_rich.important_unknown_recall,
        hard=False,
    )
    hard_failures = tuple(item.metric for item in findings if item.hard)
    return ProductReleaseReport(
        floors_version=floors.version,
        reason=floors.reason,
        findings=tuple(findings),
        hard_failures=hard_failures,
        observations=observations,
    )


def require_product_release_gate(report: ProductReleaseReport) -> None:
    if report.findings:
        parts = [item.detail for item in report.findings]
        raise AssertionError(f"product release gate {report.floors_version} failed: " + "; ".join(parts))


def floors_version_fingerprint(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("floors file must be an object")
    return f"{payload.get('version')}:{payload.get('reason')}"
