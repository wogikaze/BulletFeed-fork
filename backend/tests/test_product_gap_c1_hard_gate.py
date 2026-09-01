from __future__ import annotations

from pathlib import Path

from app.evaluation.product_gap_c1_hard_gate import evaluate_c1_hard_gate

GOLD_V1 = Path(__file__).parent / "gold" / "product_gap" / "c1"
GOLD_V2 = GOLD_V1 / "v2"


def test_v1_is_not_final_blind_and_needs_artifacts() -> None:
    report = evaluate_c1_hard_gate(GOLD_V1)
    assert report["completion_gate_pass"] is False
    assert report["gates"]["g0"]["completion_gate_pass"] is False
    assert "dataset_not_final_blind_eligible" in report["gates"]["g0"]["blockers"]
    assert report["gates"]["g1"]["status"] == "measurement_absent"
    assert report["gates"]["g2"]["status"] == "measurement_absent"
    assert any("g1_measurement_absent" in item for item in report["blockers"])


def test_v2_hard_gate_reads_artifacts_only() -> None:
    if not (GOLD_V2 / "sources.json").is_file():
        return
    report = evaluate_c1_hard_gate(GOLD_V2)
    assert report["dataset_version"] == "product-gap-c1-g0-v2"
    assert report["completion_gate_pass"] is False
    assert "operator_attestation_pending" in report["gates"]["g0"]["blockers"]
    assert "g3_family_regression_unmeasured" in report["gates"]["g3"]["blockers"]
