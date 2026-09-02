from scripts.build_rc_evidence_report import _repository_sha, build_report


def test_rc_evidence_report_references_all_current_mission_artifacts(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "test-sha")

    report = build_report()

    assert report["repository_sha"] == "test-sha"
    assert report["completion_gate_pass"] is False
    assert report["field_eval"]["executed"] is False
    assert report["field_eval"]["start_ok_with_one_person"] is True
    assert report["field_eval"]["completion_target_participants"] == 5
    assert report["field_eval"]["source_of_truth"] == "GET /v1/me/feed-sessions/metrics"
    assert set(report["missions"]) == {"m1", "m2", "m3", "m4", "m5", "m6", "m7"}
    assert report["missions"]["m1"]["evidence_checks"]["persona_count"] is True
    assert report["missions"]["m1"]["api_qualification"]["evidence_checks"]["stage_failures"] is True
    assert report["missions"]["m2"]["evidence_checks"]["blind_isolation"] is True
    assert report["missions"]["m3"]["evidence_checks"]["replay_failures"] is True
    assert report["missions"]["m3"]["live_sample"]["evidence_checks"]["success_rate"] is True
    quality = report["missions"]["m3"]["source_discovery_quality"]
    assert quality["evidence_checks"]["deterministic_execution"] is True
    assert quality["evidence_checks"]["live_qualification_separate"] is True
    assert quality["evidence_checks"]["quality_floors"] is False
    assert (
        report["missions"]["m3"]["observed_failure_remediation"]["decision"]
        == "remediation_not_required"
    )
    assert report["missions"]["m4"]["evidence_checks"]["acceptance_gradle"] is True
    assert report["missions"]["m5"]["evidence_checks"]["session_persisted"] is True
    assert report["missions"]["m5"]["host_recovery"]["evidence_checks"]["ready_after_restart"] is True
    assert (
        report["missions"]["m5"]["host_recovery"]["evidence_checks"]["persistent_volume_disk_full"]
        is True
    )
    assert report["missions"]["m5"]["host_recovery"]["evidence_checks"]["ext4_loop_not_tmpfs"] is True
    assert report["missions"]["m6"]["root_cause_analysis"]["evidence_checks"][
        "responsible_paths_identified"
    ] is True
    assert report["missions"]["m6"]["capacity_diagnosis"]["evidence_checks"][
        "javascript_capacity_mix"
    ] is True
    assert report["missions"]["m6"]["capacity_diagnosis"]["evidence_checks"][
        "package_saturated"
    ] is True
    oneshot = report["missions"]["m6"]["oneshot_blind"]
    assert oneshot["evidence_checks"]["ran_once"] is True
    assert oneshot["evidence_checks"]["not_retuned"] is True
    assert oneshot["evidence_checks"]["not_claimed_pass"] is True
    assert oneshot["aggregate_status"] == "not_scorable"
    assert oneshot["status"] == "not_scorable"
    assert oneshot["thin_holdout"] is True
    assert "M5 long-running snapshot" not in " ".join(report["unmet_gate_items"])
    assert "M3 longitudinal" not in " ".join(report["unmet_gate_items"])
    assert report["missions"]["m3"]["longitudinal_t1"]["evidence_checks"][
        "live_collected"
    ] is True
    assert any("#171" in item for item in report["unmet_gate_items"])
    assert any("not_scorable" in item for item in report["unmet_gate_items"])
    assert any("Source-discovery" in item for item in report["unmet_gate_items"])
    assert any("not PASS" in item for item in report["unmet_gate_items"])
    assert report["missions"]["m7"]["evidence_checks"]["no_user_id_in_report"] is True
    assert any("GitHub OAuth" in item for item in report["human_only_or_field_validation"])
    assert any("#327" in item for item in report["human_only_or_field_validation"])


def test_rc_evidence_report_resolves_git_sha_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    sha = _repository_sha()
    assert sha
    assert len(sha) >= 7
    report = build_report()
    assert report["repository_sha"] == sha
    assert report["completion_gate_pass"] is False
    assert report["status"] == "pre_field_release_candidate"
