from scripts.build_rc_evidence_report import build_report


def test_rc_evidence_report_references_all_current_mission_artifacts(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "test-sha")

    report = build_report()

    assert report["repository_sha"] == "test-sha"
    assert report["completion_gate_pass"] is False
    assert set(report["missions"]) == {"m1", "m2", "m3", "m4", "m5", "m6", "m7"}
    assert report["missions"]["m1"]["evidence_checks"]["persona_count"] is True
    assert report["missions"]["m1"]["api_qualification"]["evidence_checks"]["stage_failures"] is True
    assert report["missions"]["m2"]["evidence_checks"]["blind_isolation"] is True
    assert report["missions"]["m3"]["evidence_checks"]["replay_failures"] is True
    assert report["missions"]["m3"]["live_sample"]["evidence_checks"]["success_rate"] is True
    assert (
        report["missions"]["m3"]["observed_failure_remediation"]["decision"]
        == "remediation_not_required"
    )
    assert report["missions"]["m4"]["evidence_checks"]["acceptance_gradle"] is True
    assert report["missions"]["m5"]["evidence_checks"]["session_persisted"] is True
    assert report["missions"]["m5"]["host_recovery"]["evidence_checks"]["ready_after_restart"] is True
    assert report["missions"]["m6"]["root_cause_analysis"]["evidence_checks"][
        "responsible_paths_identified"
    ] is True
    assert report["missions"]["m7"]["evidence_checks"]["no_user_id_in_report"] is True
