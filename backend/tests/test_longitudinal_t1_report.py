import json
from pathlib import Path

from app.evaluation.longitudinal_qualification import PROTOCOL_VERSION

REPORT = (
    Path(__file__).resolve().parent
    / "gold"
    / "source_qualification"
    / "v01"
    / "longitudinal_t1_report.json"
)


def test_live_t1_report_is_complete_and_does_not_store_bodies() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload["protocol_version"] == PROTOCOL_VERSION
    assert payload["live_collected"] is True
    assert payload["pair_count"] == 16
    assert payload["complete_pair_count"] == 16
    assert payload["unavailable_count"] == 0
    assert payload["observed_failure_count"] == 0
    assert payload["remediation"] == "remediation_not_required"
    assert payload["missing_second_fetch_not_counted_as_update"] is True
    assert "updated" in payload["outcome_counts"]
    assert "unchanged" in payload["outcome_counts"]
    for pair in payload["pairs"]:
        t1 = pair["t1"]
        assert t1 is not None
        assert "body" not in t1
        assert pair["outcome"] != "unavailable"
        if pair["outcome"] == "updated":
            assert t1["content_hash"] != pair["t0"]["content_hash"]
        if pair["outcome"] == "unchanged":
            assert t1["content_hash"] == pair["t0"]["content_hash"]
