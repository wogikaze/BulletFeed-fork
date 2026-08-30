from pathlib import Path

from app.evaluation.source_qualification import (
    TARGET_LIVE_ENDPOINTS,
    TARGET_REPLAY_CASES,
    load_and_evaluate_source_qualification,
    qualification_release_violations,
)

_CORPUS = Path(__file__).parent / "gold" / "real_world_validation" / "v01"


def test_recorded_live_artifacts_have_replay_identity() -> None:
    report = load_and_evaluate_source_qualification(_CORPUS)

    assert report.live_endpoint_count > 0
    assert report.replay_case_count >= sum(report.source_family_counts.values()) * 2
    assert report.replay_failed_count == 0
    assert "recorded_fetch" in report.scenario_counts
    assert "duplicate_delivery" in report.scenario_counts
    assert report.scenario_counts["reordered_payload"] > 0
    assert report.scenario_counts["malformed_payload"] > 0
    assert report.scenario_counts["oversize_guard"] > 0
    assert report.scenario_counts["redirect_private_guard"] > 0
    assert report.scenario_counts["ssrf_private_ip_guard"] > 0
    assert report.scenario_counts["rate_limit_guard"] > 0
    assert report.scenario_counts["server_error_guard"] > 0
    assert report.scenario_counts["malformed_xml_guard"] > 0
    package_metrics = report.source_family_metrics["package_registry"]
    assert package_metrics["endpoint_count"] == 500
    assert package_metrics["recorded_fetch_success_rate"] == 1.0
    assert package_metrics["duplicate_delivery_failure_rate"] == 0.0
    assert package_metrics["update_detection"]["status"] == "not_recorded"


def test_qualification_floors_are_explicit() -> None:
    report = load_and_evaluate_source_qualification(_CORPUS)
    violations = qualification_release_violations(report)

    if report.live_endpoint_count < TARGET_LIVE_ENDPOINTS:
        assert any("live_endpoint_count" in item for item in violations)
    if report.replay_case_count < TARGET_REPLAY_CASES:
        assert any("replay_case_count" in item for item in violations)
