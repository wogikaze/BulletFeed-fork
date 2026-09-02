import json
import hashlib
from pathlib import Path

from scripts.build_rc_evidence_report import _m2_gate, _repository_sha, build_report


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
    assert report["missions"]["m2"]["evidence_checks"]["full_pipeline_attribution"] is False
    assert (
        report["missions"]["m2"]["pipeline_attribution"]["provenance"]["trace_scope"]
        == "m1_m7_deterministic_journey"
    )
    assert report["missions"]["m2"]["pipeline_artifact"].endswith(
        "pipeline_stage_attribution.json"
    )
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


def test_m2_pipeline_attribution_requires_historical_corpus_scope() -> None:
    report = {
        "dataset_version": "real-world-validation-v0.2",
        "capacity": {"meets_targets": True},
        "metrics": {
            "blind_records_loaded": False,
            "uncertainty": {"headline": {"at_10": {"status": "available"}}},
            "failure_taxonomy": {"status": "available"},
        },
    }
    complete = {
        "status": "available",
        "coverage_status": "complete",
        "labels_loaded": False,
        "ranking_inference_used": False,
        "provenance": {"trace_scope": "m1_m7_deterministic_journey"},
    }

    assert _m2_gate(report, complete)["evidence_checks"]["full_pipeline_attribution"] is False

    source = Path(__file__)
    complete["provenance"].update(
        {
            "trace_scope": "m2_historical_corpus",
            "source_artifact": str(source),
            "source_artifact_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "dataset_version": "real-world-validation-v0.2",
            "harness_version": "m2-harness-v1",
        }
    )
    complete["tenant_boundary"] = {
        "tenant_boundary_unknown_count": 0,
        "tenant_boundary_violation_count": 0,
    }
    assert _m2_gate(report, complete)["evidence_checks"]["full_pipeline_attribution"] is True


def test_m2_pipeline_attribution_rejects_stale_source_hash(tmp_path) -> None:
    source = tmp_path / "trace.json"
    source.write_text("{}", encoding="utf-8")
    report = {
        "dataset_version": "real-world-validation-v0.2",
        "capacity": {"meets_targets": True},
        "metrics": {
            "blind_records_loaded": False,
            "uncertainty": {"headline": {"at_10": {"status": "available"}}},
            "failure_taxonomy": {"status": "available"},
        },
    }
    pipeline = {
        "status": "available",
        "coverage_status": "complete",
        "labels_loaded": False,
        "ranking_inference_used": False,
        "provenance": {
            "source_artifact": str(source),
            "source_artifact_sha256": "0" * 64,
            "trace_scope": "m2_historical_corpus",
            "dataset_version": "real-world-validation-v0.2",
            "harness_version": "m2-harness-v1",
        },
        "tenant_boundary": {
            "tenant_boundary_unknown_count": 0,
            "tenant_boundary_violation_count": 0,
        },
    }

    gate = _m2_gate(report, pipeline)

    assert gate["evidence_checks"]["pipeline_source_hash"] is False
    assert gate["evidence_checks"]["full_pipeline_attribution"] is False


def test_rc_evidence_report_resolves_git_sha_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    sha = _repository_sha()
    assert sha
    assert len(sha) >= 7
    report = build_report()
    assert report["repository_sha"] == sha
    assert report["completion_gate_pass"] is False
    assert report["status"] == "pre_field_release_candidate"


def test_rc_evidence_report_can_include_runtime_android_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "test-sha")
    android_report = {
        "repository_sha": "test-sha",
        "backend_status": "passed",
        "field_validation": False,
        "completion_gate_pass": False,
        "android": {
            "acceptance": {
                "status": "passed",
                "gradle_exit_code": 0,
                "backend": "same_clean_room_backend",
            },
            "release_build": {
                "status": "passed",
                "artifact_present": True,
            },
            "lifecycle": {
                "status": "not_available",
                "install": {"status": "not_available"},
                "upgrade": {"status": "not_available"},
                "recovery": {"status": "not_available"},
            },
            "limitations": ["field excluded"],
        },
    }
    path = tmp_path / "m7-android.json"
    path.write_text(json.dumps(android_report), encoding="utf-8")

    report = build_report(path)

    integrated = report["missions"]["m7"]["integrated_android"]
    assert integrated["status"] == "partial"
    assert integrated["lifecycle_status"] == "not_available"
    assert integrated["evidence_checks"]["same_clean_room_backend"] is True
    assert integrated["evidence_checks"]["repository_sha_matches"] is True
    assert integrated["evidence_checks"]["signed_release"] is False
    assert integrated["evidence_checks"]["install_evidence"] is False
    assert integrated["evidence_checks"]["upgrade_evidence"] is False
    assert integrated["evidence_checks"]["recovery_evidence"] is False
    assert integrated["evidence_checks"]["field_validation_excluded"] is True
    assert integrated["evidence_checks"]["completion_gate_not_claimed"] is True

    android_report["android"]["lifecycle"]["status"] = "failed"
    path.write_text(json.dumps(android_report), encoding="utf-8")
    failed_lifecycle = build_report(path)["missions"]["m7"]["integrated_android"]
    assert failed_lifecycle["status"] == "fail"

    android_report["android"]["lifecycle"]["status"] = "not_available"
    android_report["repository_sha"] = "different-sha"
    path.write_text(json.dumps(android_report), encoding="utf-8")
    mismatched = build_report(path)["missions"]["m7"]["integrated_android"]
    assert mismatched["status"] == "fail"
    assert mismatched["evidence_checks"]["repository_sha_matches"] is False
