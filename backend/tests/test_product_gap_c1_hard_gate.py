from __future__ import annotations

from pathlib import Path

from app.evaluation.product_gap_c1_hard_gate import evaluate_c1_hard_gate

GOLD = Path(__file__).parent / "gold" / "product_gap" / "c1"


def test_replay_metrics_cannot_close_hard_gate() -> None:
    report = evaluate_c1_hard_gate(GOLD)

    assert report["completion_gate_pass"] is False
    assert report["gates"]["g1"]["deterministic_replay_pass"] is False
    assert report["gates"]["g1"]["completion_gate_pass"] is False
    assert report["gates"]["g2"]["evidence"] == "production_curated_seed_discovery_vs_g0_labels"
    assert report["gates"]["g2"]["completion_gate_pass"] is False
    assert report["gates"]["g3"]["reported_bulletfeed_universe_recall_accepted"] is False
    assert report["gates"]["g3"]["reported_breadth_superiority_accepted"] is False
    assert report["gates"]["g4"]["update_recall"] is None
    assert report["gates"]["g4"]["update_precision"] is None
    assert report["gates"]["g5"]["deterministic_ssrf_pass"] is False
    assert any("independent_topic_to_source_discovery_unmeasured" in item for item in report["blockers"])
    assert any("live_rss_oracle_parity_unmeasured" in item for item in report["blockers"])
