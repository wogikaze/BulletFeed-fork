from __future__ import annotations

import json
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
    assert report["gates"]["g1"]["status"] == "measured"
    assert report["gates"]["g1"]["completion_gate_pass"] is False
    assert "g1_feed_recall" in report["gates"]["g1"]["blockers"]
    assert report["gates"]["g3"]["completion_gate_pass"] is False
    assert report["gates"]["g4"]["completion_gate_pass"] is False
    assert "g4_n_lt_10" in report["gates"]["g4"]["blockers"]
    assert "g4_live_blog_unmeasured" in report["gates"]["g4"]["blockers"]
    assert report["gates"]["g5"]["status"] == "measured"
    assert report["gates"]["g5"]["completion_gate_pass"] is True
    assert report["gates"]["g5"]["blockers"] == []


def test_perfect_g4_fixture_scores_do_not_pass_hard_gate_when_n_lt_10(tmp_path: Path) -> None:
    gold = tmp_path / "c1"
    gold.mkdir()
    for name in ("g0_freeze.json", "sources.json", "attestation.json"):
        (gold / name).write_bytes((GOLD_V1 / name).read_bytes())
    (gold / "measurements").mkdir()
    (gold / "measurements" / "g4_measurement.json").write_text(
        json.dumps(
            {
                "sample_count": 4,
                "live_blog_measured": False,
                "metrics": {
                    "body_success": 1.0,
                    "important_body_recall": 1.0,
                    "update_recall": 1.0,
                    "update_precision": 1.0,
                    "boilerplate_fp": 0.0,
                    "article_split": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
    report = evaluate_c1_hard_gate(gold)
    assert report["completion_gate_pass"] is False
    assert "g4_n_lt_10" in report["gates"]["g4"]["blockers"]
    assert "g4_live_blog_unmeasured" in report["gates"]["g4"]["blockers"]
