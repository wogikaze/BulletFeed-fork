from app.evaluation.gold import GoldEvaluationReport
from app.evaluation.split_summary import summarize_split_reports


def report(bundle_id: str, accuracy: float) -> GoldEvaluationReport:
    return GoldEvaluationReport(
        bundle_id=bundle_id,
        revision_accuracy=accuracy,
        delta_precision=1.0,
        delta_recall=1.0,
        repetition_rate=0.0,
        correction_recall=1.0,
        evidence_coverage=1.0,
        unsupported_claim_count=0,
        false_merge_count=0,
        false_split_count=0,
    )


def test_split_report_keeps_pilot_and_blind_metrics_separate():
    summary = summarize_split_reports(
        (
            ("pilot", report("pilot-a", 1.0)),
            ("pilot", report("pilot-b", 0.8)),
            ("blind", report("blind-a", 0.6)),
        )
    )

    assert summary["pilot"].bundles == 2
    assert summary["pilot"].revision_accuracy == 0.9
    assert summary["blind"].bundles == 1
    assert summary["blind"].revision_accuracy == 0.6
    assert summary["blind"].as_dict()["split"] == "blind"
