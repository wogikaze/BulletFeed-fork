from __future__ import annotations

from dataclasses import dataclass

from app.evaluation.gold import GoldEvaluationReport


@dataclass(frozen=True)
class ReleaseGateThresholds:
    revision_accuracy: float = 0.95
    delta_precision: float = 0.95
    delta_recall: float = 0.95
    repetition_rate: float = 0.05
    correction_recall: float = 1.0
    evidence_coverage: float = 1.0
    unsupported_claim_count: int = 0
    false_merge_count: int = 0
    false_split_count: int = 0


DEFAULT_RELEASE_GATE = ReleaseGateThresholds()


def release_gate_violations(
    report: GoldEvaluationReport,
    thresholds: ReleaseGateThresholds = DEFAULT_RELEASE_GATE,
) -> tuple[str, ...]:
    violations: list[str] = []
    if report.revision_accuracy < thresholds.revision_accuracy:
        violations.append(
            f"revision_accuracy {report.revision_accuracy:.3f} < {thresholds.revision_accuracy:.3f}"
        )
    if report.delta_precision < thresholds.delta_precision:
        violations.append(
            f"delta_precision {report.delta_precision:.3f} < {thresholds.delta_precision:.3f}"
        )
    if report.delta_recall < thresholds.delta_recall:
        violations.append(
            f"delta_recall {report.delta_recall:.3f} < {thresholds.delta_recall:.3f}"
        )
    if report.repetition_rate > thresholds.repetition_rate:
        violations.append(
            f"repetition_rate {report.repetition_rate:.3f} > {thresholds.repetition_rate:.3f}"
        )
    if report.correction_recall < thresholds.correction_recall:
        violations.append(
            f"correction_recall {report.correction_recall:.3f} < {thresholds.correction_recall:.3f}"
        )
    if report.evidence_coverage < thresholds.evidence_coverage:
        violations.append(
            f"evidence_coverage {report.evidence_coverage:.3f} < {thresholds.evidence_coverage:.3f}"
        )
    if report.unsupported_claim_count > thresholds.unsupported_claim_count:
        violations.append(
            f"unsupported_claim_count {report.unsupported_claim_count} > {thresholds.unsupported_claim_count}"
        )
    if report.false_merge_count > thresholds.false_merge_count:
        violations.append(
            f"false_merge_count {report.false_merge_count} > {thresholds.false_merge_count}"
        )
    if report.false_split_count > thresholds.false_split_count:
        violations.append(
            f"false_split_count {report.false_split_count} > {thresholds.false_split_count}"
        )
    return tuple(violations)


def require_release_gate(
    report: GoldEvaluationReport,
    thresholds: ReleaseGateThresholds = DEFAULT_RELEASE_GATE,
) -> None:
    violations = release_gate_violations(report, thresholds)
    if violations:
        raise AssertionError(f"Gold bundle {report.bundle_id} failed release gate: " + "; ".join(violations))
