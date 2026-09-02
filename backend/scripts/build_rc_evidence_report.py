"""Build the versioned pre-field Release Candidate evidence report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = BACKEND / "tests" / "gold"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "release_candidate" / "v01" / "rc_evidence_report.json"
REPORT_VERSION = "m7-rc-evidence-v1"

ARTIFACTS = {
    "m1": EVIDENCE_ROOT / "m1_personas" / "v01" / "deterministic_baseline.json",
    "m1_api": EVIDENCE_ROOT / "m1_personas" / "v01" / "api_qualification.json",
    "m2": EVIDENCE_ROOT / "real_world_validation" / "v01" / "m2_readiness_report.json",
    "m2_pipeline": EVIDENCE_ROOT
    / "real_world_validation"
    / "v01"
    / "pipeline_stage_attribution.json",
    "m3": EVIDENCE_ROOT / "source_qualification" / "v01" / "report.json",
    "m3_live": EVIDENCE_ROOT / "source_qualification" / "v01" / "live_sample_200_report.json",
    "m3_t1": EVIDENCE_ROOT / "source_qualification" / "v01" / "longitudinal_t1_report.json",
    "source_discovery_quality": EVIDENCE_ROOT
    / "source_discovery"
    / "v02"
    / "current_main_measurement.json",
    "m4_android": EVIDENCE_ROOT / "android_acceptance" / "v01" / "acceptance_report.json",
    "m5": EVIDENCE_ROOT / "recovery" / "v01" / "process_recovery_report.json",
    "m5_host": EVIDENCE_ROOT / "recovery" / "v01" / "host_recovery_report.json",
    "m6": EVIDENCE_ROOT / "m6" / "v01" / "top3_selection.json",
    "m6_root_cause": EVIDENCE_ROOT / "m6" / "v01" / "root_cause_report.json",
    "m6_capacity": EVIDENCE_ROOT / "m6" / "v01" / "top3_capacity_diagnosis.json",
    "m6_oneshot_blind": EVIDENCE_ROOT / "m6" / "v01" / "oneshot_blind_aggregate.json",
    "m7_backend": EVIDENCE_ROOT / "clean_room" / "v01" / "backend_report.json",
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def _relative(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()


def _repository_sha() -> str | None:
    env_sha = os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha
    git = shutil.which("git")
    if git is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"],
            cwd=BACKEND.parent,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    sha = completed.stdout.strip()
    return sha or None


def _m1_gate(report: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "persona_count": report.get("persona_count", 0) >= 30,
        "unexpected_empty_feed": report.get("unexpected_empty_feed", 1) == 0,
        "broken_evidence": report.get("broken_evidence", 1) == 0,
        "tenant_leak": report.get("tenant_leak", 1) == 0,
        "unsafe_suppression": report.get("unsafe_suppression", 1) == 0,
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "execution_mode": report.get("mode", "unknown"),
        "note": "The checked-in harness is deterministic fixture mode, not 30 real Android journeys.",
    }


def _m2_gate(
    report: dict[str, Any],
    pipeline_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capacity = report.get("capacity", {})
    metrics = report.get("metrics", {})
    pipeline = pipeline_report or report.get("pipeline_attribution", {})
    provenance = pipeline.get("provenance", {})
    tenant_boundary = pipeline.get("tenant_boundary", {})
    source_artifact = provenance.get("source_artifact")
    source_path = (
        Path(source_artifact)
        if isinstance(source_artifact, str) and Path(source_artifact).is_absolute()
        else BACKEND / source_artifact
        if isinstance(source_artifact, str)
        else None
    )
    source_hash_matches = False
    if source_path is not None and source_path.is_file():
        source_hash_matches = (
            hashlib.sha256(source_path.read_bytes()).hexdigest()
            == provenance.get("source_artifact_sha256")
        )
    pipeline_metadata_valid = (
        provenance.get("trace_scope") == "m2_historical_corpus"
        and provenance.get("dataset_version") == report.get("dataset_version")
        and bool(provenance.get("harness_version"))
    )
    pipeline_tenant_boundary = (
        tenant_boundary.get("tenant_boundary_unknown_count") == 0
        and tenant_boundary.get("tenant_boundary_violation_count") == 0
    )
    checks = {
        "capacity_targets": bool(capacity.get("meets_targets")),
        "blind_isolation": metrics.get("blind_records_loaded") is False,
        "uncertainty": metrics.get("uncertainty", {})
        .get("headline", {})
        .get("at_10", {})
        .get("status")
        == "available",
        "failure_taxonomy": metrics.get("failure_taxonomy", {}).get("status") == "available",
        "pipeline_source_hash": source_hash_matches,
        "pipeline_metadata": pipeline_metadata_valid,
        "pipeline_tenant_boundary": pipeline_tenant_boundary,
        "full_pipeline_attribution": (
            pipeline.get("status") == "available"
            and pipeline.get("coverage_status") == "complete"
            and pipeline.get("labels_loaded") is False
            and pipeline.get("ranking_inference_used") is False
            and source_hash_matches
            and pipeline_metadata_valid
            and pipeline_tenant_boundary
        ),
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "capacity": capacity,
        "stage_attribution": metrics.get("stage_attribution", {}),
        "pipeline_attribution": pipeline,
        "pipeline_validation": {
            "source_artifact_hash_matches": source_hash_matches,
            "metadata_valid": pipeline_metadata_valid,
        },
        "note": (
            "Ranking misses remain ranking-only; acquisition/projection/evidence attribution "
            "uses explicit journey trace stages only. The checked-in M1/M7 deterministic "
            "journey trace is not M2 historical-corpus evidence."
        ),
    }


def _m1_api_gate(report: dict[str, Any]) -> dict[str, Any]:
    stage_failures = report.get("stage_failure_counts", {})
    checks = {
        "persona_count": report.get("persona_count", 0) >= 30,
        "failed_personas": not report.get("failed_persona_ids"),
        "unexpected_empty_feed": report.get("unexpected_empty_feed", 1) == 0,
        "broken_evidence": report.get("broken_evidence", 1) == 0,
        "tenant_leak": report.get("tenant_leak", 1) == 0,
        "stage_failures": not any(stage_failures.values()),
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "execution_mode": report.get("mode", "unknown"),
        "metrics": report.get("metrics", {}),
        "note": (
            "API state transitions and deterministic worker orchestration pass; Android surface "
            "breadth and live source transport remain separate gates."
        ),
    }


def _m3_gate(report: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "live_endpoint_floor": report.get("live_endpoint_count", 0) >= 200,
        "replay_floor": report.get("replay_case_count", 0) >= 1000,
        "replay_failures": report.get("replay_failed_count", 1) == 0,
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "source_family_counts": report.get("source_family_counts", {}),
        "scenario_counts": report.get("scenario_counts", {}),
        "limitations": report.get("limitations", []),
    }


def _source_discovery_quality_gate(report: dict[str, Any]) -> dict[str, Any]:
    live = report.get("live_qualification") or {}
    authority = report.get("authority") or {}
    checks = {
        "deterministic_execution": report.get("execution_mode") == "deterministic_fixture",
        "blind_not_read": report.get("blind_read") is False,
        "gold_not_injected": report.get("gold_injected") is False,
        "human_gold_not_claimed": report.get("human_gold") is False,
        "no_builtin_hints": report.get("hint_scope") == "no_builtin_hints",
        "live_qualification_separate": live.get("included_in_metrics") is False,
        "authority_breakdown": all(
            name in authority for name in ("primary", "secondary", "discovery_only")
        ),
        "topic_breakdown": bool(report.get("by_topic")),
        "family_breakdown": bool(report.get("by_family")),
        "failure_breakdown": all(
            name in (report.get("failure_class_counts") or {})
            for name in ("acquisition_failed", "extraction_failed")
        ),
    }
    quality_floors_pass = (
        report.get("passed") is True
        and report.get("evaluation_status") == "scored"
    )
    evidence_pass = all(checks.values())
    return {
        "status": "pass" if evidence_pass and quality_floors_pass else "partial" if evidence_pass else "fail",
        "evidence_checks": {**checks, "quality_floors": quality_floors_pass},
        "metrics": report.get("metrics", {}),
        "outcome_counts": report.get("outcome_counts", {}),
        "failure_class_counts": report.get("failure_class_counts", {}),
        "violations": report.get("violations", []),
        "note": (
            "Deterministic topic discovery quality is reported separately from live source "
            "qualification; a partial status preserves observed floor failures."
        ),
    }


def _m4_gate(report: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "backend_health": report.get("backend_health") == "passed",
        "acceptance_gradle": report.get("gradle_exit_code") == 0,
        "acceptance_status": report.get("status") == "passed",
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "test_class": report.get("test_class"),
        "note": "The release APK is retained as the corresponding Android Actions artifact.",
    }


def _m3_live_gate(report: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "endpoint_floor": report.get("endpoint_count", 0) >= 200,
        "success_rate": report.get("success_rate") == 1.0,
        "failure_dimensions_empty": not report.get("failure_dimensions"),
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "endpoint_count": report.get("endpoint_count"),
        "median_latency_ms": report.get("median_latency_ms"),
        "outcome_counts": report.get("outcome_counts", {}),
        "source_family_counts": report.get("source_family_counts", {}),
        "note": "This is a recorded live sample; deterministic replay remains the CI qualification.",
    }


def _m3_t1_gate(report: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "live_collected": report.get("live_collected") is True,
        "complete_pairs": report.get("pair_count") == 16
        and report.get("complete_pair_count") == 16,
        "no_unavailable": report.get("unavailable_count") == 0,
        "no_observed_failures": report.get("observed_failure_count") == 0,
        "remediation_not_required": report.get("remediation") == "remediation_not_required",
        "missing_t1_not_updated": report.get("missing_second_fetch_not_counted_as_update")
        is True,
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "outcome_counts": report.get("outcome_counts", {}),
        "by_source_family": report.get("by_source_family", {}),
        "note": (
            "Recorded live t1 hashes/headers only; bodies are not stored. "
            "Ordinary PR CI does not re-fetch live sources."
        ),
    }


def _m3_observed_failure_gate(
    replay_report: dict[str, Any],
    live_report: dict[str, Any],
) -> dict[str, Any]:
    live_failure_dimensions = live_report.get("failure_dimensions", {})
    observed_failure_count = sum(
        int(value)
        for value in live_failure_dimensions.values()
        if isinstance(value, int | float)
    )
    remediation_required = observed_failure_count > 0
    checks = {
        "live_sample_success": live_report.get("success_rate") == 1.0,
        "replay_failures": replay_report.get("replay_failed_count", 1) == 0,
        "observed_failure_count_recorded": isinstance(live_failure_dimensions, dict),
        "remediation_not_required": not remediation_required,
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "decision": "remediation_required" if remediation_required else "remediation_not_required",
        "observed_failure_count": observed_failure_count,
        "failure_dimensions": live_failure_dimensions,
        "evidence_checks": checks,
        "note": (
            "No live failure cluster was observed; #164 is completed as "
            "`remediation_not_required`. Any future longitudinal failure belongs to #283 "
            "and reopens concrete remediation."
        ),
    }


def _m5_gate(report: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "status": report.get("status") == "passed",
        "worker_restart": report.get("worker_restart") is True,
        "api_restart": report.get("api_restart") is True,
        "session_persisted": report.get("session_persisted") is True,
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "residual_risks": report.get("residual_risks", []),
    }


def _m5_host_gate(report: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "status": report.get("status") == "passed",
        "api_restart": report.get("api_restart") is True,
        "worker_restart": report.get("worker_restart") is True,
        "session_persisted": report.get("session_persisted") is True,
        "ready_after_restart": report.get("ready_after_restart") is True,
        "filesystem_fault_injection": report.get("filesystem_fault_injection") is True,
        "persistent_volume_disk_full": report.get("persistent_volume_disk_full") is True,
        "ext4_loop_not_tmpfs": (
            isinstance(report.get("persistent_volume_disk_full_report"), dict)
            and report["persistent_volume_disk_full_report"].get("medium") == "ext4_loop"
            and report["persistent_volume_disk_full_report"].get("tmpfs_substituted") is False
        ),
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "repository_sha": report.get("repository_sha"),
        "workflow_run_id": report.get("workflow_run_id"),
        "residual_risks": report.get("residual_risks", []),
    }


def _m6_root_cause_gate(report: dict[str, Any]) -> dict[str, Any]:
    clusters = report.get("clusters", [])
    checks = {
        "analysis_only": report.get("status") == "analysis_only",
        "top3_analyzed": len(clusters) == 3,
        "responsible_paths_identified": all(
            bool(cluster.get("responsible_code_paths")) for cluster in clusters
        ),
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "stage_attribution": report.get("stage_attribution"),
        "root_cause_hypotheses": {
            cluster.get("persona_family"): cluster.get("root_cause_hypothesis")
            for cluster in clusters
        },
        "note": (
            "Root-cause analysis is ranking-only; no production remediation or blind tuning "
            "was performed."
        ),
    }


def _m6_gate(report: dict[str, Any]) -> dict[str, Any]:
    clusters = report.get("clusters", [])
    checks = {
        "top3_selected": report.get("status") == "selected_for_dev_remediation"
        and len(clusters) == 3,
        "representative_case_floor": all(
            cluster.get("representative_case_count", 0) >= 20 for cluster in clusters
        ),
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "note": (
            "Top-3 family IU@10 is k=10 capacity after identity/recency/production ranker. "
            "Do not run #171 to chase family IU@10."
        ),
    }


def _m6_capacity_gate(report: dict[str, Any]) -> dict[str, Any]:
    families = report.get("persona_families", {})
    package = families.get("package_release_manager", {})
    javascript = families.get("javascript_tooling_maintainer", {})
    checks = {
        "not_blind": report.get("blind_read") is False and report.get("human_gold") is False,
        "package_saturated": package.get("k10_saturated_profiles") == 4,
        "javascript_capacity_mix": javascript.get("k10_saturated_profiles") == 2
        and javascript.get("vacuous_perfect_recall_profiles") == 2,
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "note": (
            "Saturated users already fill top-10 with important-unknown. "
            "Vacuous IU recall 1.0 for empty IU sets is the existing metric contract."
        ),
    }


def _m6_oneshot_blind_gate(report: dict[str, Any]) -> dict[str, Any]:
    holdout = report.get("holdout") or {}
    aggregate_status = report.get("aggregate_status")
    ran_once = (
        report.get("status") == "oneshot_blind_recorded"
        and report.get("oneshot") is True
        and report.get("retune") is False
    )
    thin_holdout = (
        int(holdout.get("judgments") or 0) <= 1
        or int(holdout.get("scored_judgments") or 0) == 0
    )
    checks = {
        "ran_once": ran_once,
        "not_retuned": report.get("retune") is False,
        "production_code_unchanged": report.get("production_code_unchanged") is True,
        "not_human_gold": report.get("human_gold") is False,
        "aggregate_recorded": aggregate_status in {"available", "not_scorable"},
        "not_claimed_pass": aggregate_status != "pass",
    }
    if ran_once and aggregate_status == "not_scorable":
        status = "not_scorable"
    elif ran_once and aggregate_status == "available":
        status = "recorded"
    else:
        status = "fail"
    return {
        "status": status,
        "evidence_checks": checks,
        "aggregate_status": aggregate_status,
        "oneshot": report.get("oneshot"),
        "retune": report.get("retune"),
        "frozen_sha": report.get("repository_sha"),
        "thin_holdout": thin_holdout,
        "holdout": {
            "events": holdout.get("events"),
            "real_events": holdout.get("real_events"),
            "profiles": holdout.get("profiles"),
            "judgments": holdout.get("judgments"),
            "scored_judgments": holdout.get("scored_judgments"),
        },
        "note": (
            "#171 ran once after production freeze. "
            "aggregate_status is not_scorable because the reserved holdout is thin "
            "(1 judgment, 0 scored). This is not M6 blind PASS. "
            "Do not retune or expand the holdout."
        ),
    }


def _m7_gate(report: dict[str, Any]) -> dict[str, Any]:
    stages = report.get("stages", [])
    checks = {
        "backend_status": report.get("status") == "passed",
        "all_backend_stages": bool(stages) and all(stage.get("ok") is True for stage in stages),
        "no_user_id_in_report": "user_id" not in report,
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "limitations": report.get("limitations", []),
        "note": "This is backend clean-room evidence; Android release and field validation remain separate.",
    }


def _unmet_gate_items(missions: dict[str, Any]) -> list[str]:
    unmet = [
        "M1 Android journey and cross-surface breadth for all 30 personas",
    ]
    source_quality = missions.get("m3", {}).get("source_discovery_quality", {})
    if not source_quality.get("evidence_checks", {}).get("quality_floors", False):
        unmet.append(
            "Source-discovery topic/family quality floors and failure taxonomy remain unmet"
        )
    t1 = missions.get("m3", {}).get("longitudinal_t1", {})
    if t1.get("status") != "partial":
        unmet.append("M3 longitudinal per-source update evidence (#283)")
    unmet.append(
        "M4 broad phone/tablet/a11y/error/offline qualification and release field validation"
    )
    m2 = missions.get("m2", {})
    if not m2.get("evidence_checks", {}).get("full_pipeline_attribution", False):
        unmet.append(
            "M2 acquisition/projection/evidence attribution for the historical corpus "
            "(no in-scope M2 pipeline trace)"
        )
    oneshot = missions.get("m6", {}).get("oneshot_blind", {})
    if oneshot.get("aggregate_status") == "not_scorable":
        unmet.append(
            "M6 one-shot blind (#171) ran once after freeze; "
            "aggregate_status=not_scorable (thin holdout); not PASS"
        )
    else:
        unmet.append("M6 one-shot blind aggregate evaluation (#171) after production freeze")
    unmet.append(
        "M7 integrated Android clean-room install/upgrade/recovery and final field-readiness decision"
    )
    return unmet


def build_report() -> dict[str, Any]:
    loaded = {name: _load(path) for name, path in ARTIFACTS.items()}
    missions = {
        "m1": {
            "artifact": _relative(ARTIFACTS["m1"]),
            "api_artifact": _relative(ARTIFACTS["m1_api"]),
            **_m1_gate(loaded["m1"]),
            "api_qualification": _m1_api_gate(loaded["m1_api"]),
        },
        "m2": {
            "artifact": _relative(ARTIFACTS["m2"]),
            "pipeline_artifact": _relative(ARTIFACTS["m2_pipeline"]),
            **_m2_gate(loaded["m2"], loaded["m2_pipeline"]),
        },
        "m3": {
            "artifact": _relative(ARTIFACTS["m3"]),
            "live_artifact": _relative(ARTIFACTS["m3_live"]),
            "longitudinal_t1_artifact": _relative(ARTIFACTS["m3_t1"]),
            **_m3_gate(loaded["m3"]),
            "live_sample": _m3_live_gate(loaded["m3_live"]),
            "source_discovery_quality": {
                "artifact": _relative(ARTIFACTS["source_discovery_quality"]),
                **_source_discovery_quality_gate(loaded["source_discovery_quality"]),
            },
            "observed_failure_remediation": _m3_observed_failure_gate(
                loaded["m3"],
                loaded["m3_live"],
            ),
            "longitudinal_t1": _m3_t1_gate(loaded["m3_t1"]),
        },
        "m4": {
            "artifact": _relative(ARTIFACTS["m4_android"]),
            **_m4_gate(loaded["m4_android"]),
        },
        "m5": {
            "artifact": _relative(ARTIFACTS["m5"]),
            "host_artifact": _relative(ARTIFACTS["m5_host"]),
            **_m5_gate(loaded["m5"]),
            "host_recovery": _m5_host_gate(loaded["m5_host"]),
        },
        "m6": {
            "artifact": _relative(ARTIFACTS["m6"]),
            "root_cause_artifact": _relative(ARTIFACTS["m6_root_cause"]),
            "capacity_artifact": _relative(ARTIFACTS["m6_capacity"]),
            "oneshot_blind_artifact": _relative(ARTIFACTS["m6_oneshot_blind"]),
            **_m6_gate(loaded["m6"]),
            "root_cause_analysis": _m6_root_cause_gate(loaded["m6_root_cause"]),
            "capacity_diagnosis": _m6_capacity_gate(loaded["m6_capacity"]),
            "oneshot_blind": _m6_oneshot_blind_gate(loaded["m6_oneshot_blind"]),
        },
        "m7": {
            "artifact": _relative(ARTIFACTS["m7_backend"]),
            **_m7_gate(loaded["m7_backend"]),
        },
    }
    return {
        "report_version": REPORT_VERSION,
        "repository_sha": _repository_sha(),
        "status": "pre_field_release_candidate",
        "completion_gate_pass": False,
        "blind_read": False,
        "missions": missions,
        "unmet_gate_items": _unmet_gate_items(missions),
        "field_eval": {
            "protocol": "docs/evaluation/field-eval-protocol.md",
            "human_blockers": "docs/operations/field-eval-human-blockers.md",
            "source_of_truth": "GET /v1/me/feed-sessions/metrics",
            "start_ok_with_one_person": True,
            "completion_target_participants": 5,
            "executed": False,
        },
        "human_only_or_field_validation": [
            "live OAuth and real-user enrollment are excluded from automated clean-room evidence",
            "public HTTPS field validation is not replaced by local fixtures",
            "public HTTPS backend, domain, and certificates are a human-only blocker",
            "GitHub OAuth client secret is a human-only production secret",
            "paid hosting is a human-only paid-service commitment",
            (
                "enrolling users other than the operator requires real-user consent; "
                "start is allowed with 1 person; #327 completion target is >=5"
            ),
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    report = build_report()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if args.check and not report["repository_sha"]:
        print("RC evidence check failed: repository_sha is missing", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
