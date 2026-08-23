import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.evaluation.gold import evaluate_statuspage_bundle
from app.evaluation.release_gate import require_release_gate


def test_statuspage_gold_pilot_measures_release_gate_metrics(database):
    path = Path(__file__).parent / "gold" / "statuspage_pilot_001.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))

    report = evaluate_statuspage_bundle(database, bundle)

    assert report.bundle_id == "statuspage-pilot-001"
    assert report.revision_accuracy == 1.0
    assert report.delta_precision == 1.0
    assert report.delta_recall == 1.0
    assert report.repetition_rate == 0.0
    assert report.correction_recall == 1.0
    assert report.evidence_coverage == 1.0
    assert report.unsupported_claim_count == 0
    assert report.false_merge_count == 0
    assert report.false_split_count == 0
    require_release_gate(report)


def test_release_gate_is_blocking_not_informational(database):
    path = Path(__file__).parent / "gold" / "statuspage_pilot_001.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    report = evaluate_statuspage_bundle(database, bundle)

    failing = replace(
        report,
        revision_accuracy=0.94,
        delta_recall=0.94,
        unsupported_claim_count=1,
    )
    with pytest.raises(
        AssertionError,
        match="revision_accuracy.*delta_recall.*unsupported_claim_count",
    ):
        require_release_gate(failing)
