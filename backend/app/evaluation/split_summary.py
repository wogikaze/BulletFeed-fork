from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Literal

from app.evaluation.gold import GoldEvaluationReport

Split = Literal["pilot", "blind"]


@dataclass(frozen=True)
class SplitMetricSummary:
    split: Split
    bundles: int
    revision_accuracy: float
    delta_precision: float
    delta_recall: float
    repetition_rate: float
    correction_recall: float
    evidence_coverage: float
    unsupported_claim_count: int
    false_merge_count: int
    false_split_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def summarize_split_reports(
    reports: Iterable[tuple[Split, GoldEvaluationReport]],
) -> dict[Split, SplitMetricSummary]:
    grouped: dict[Split, list[GoldEvaluationReport]] = {"pilot": [], "blind": []}
    for split, report in reports:
        grouped[split].append(report)

    return {split: _summarize(split, split_reports) for split, split_reports in grouped.items()}


def _summarize(split: Split, reports: list[GoldEvaluationReport]) -> SplitMetricSummary:
    if not reports:
        return SplitMetricSummary(
            split=split,
            bundles=0,
            revision_accuracy=0.0,
            delta_precision=0.0,
            delta_recall=0.0,
            repetition_rate=0.0,
            correction_recall=0.0,
            evidence_coverage=0.0,
            unsupported_claim_count=0,
            false_merge_count=0,
            false_split_count=0,
        )
    return SplitMetricSummary(
        split=split,
        bundles=len(reports),
        revision_accuracy=fmean(report.revision_accuracy for report in reports),
        delta_precision=fmean(report.delta_precision for report in reports),
        delta_recall=fmean(report.delta_recall for report in reports),
        repetition_rate=fmean(report.repetition_rate for report in reports),
        correction_recall=fmean(report.correction_recall for report in reports),
        evidence_coverage=fmean(report.evidence_coverage for report in reports),
        unsupported_claim_count=sum(report.unsupported_claim_count for report in reports),
        false_merge_count=sum(report.false_merge_count for report in reports),
        false_split_count=sum(report.false_split_count for report in reports),
    )
