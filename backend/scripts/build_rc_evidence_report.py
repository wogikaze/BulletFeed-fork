"""Build the versioned pre-field Release Candidate evidence report."""

from __future__ import annotations

import argparse
import json
import os
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
    "m3": EVIDENCE_ROOT / "source_qualification" / "v01" / "report.json",
    "m4_android": EVIDENCE_ROOT / "android_acceptance" / "v01" / "acceptance_report.json",
    "m5": EVIDENCE_ROOT / "recovery" / "v01" / "process_recovery_report.json",
    "m6": EVIDENCE_ROOT / "m6" / "v01" / "top3_selection.json",
    "m7_backend": EVIDENCE_ROOT / "clean_room" / "v01" / "backend_report.json",
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def _relative(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()


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


def _m2_gate(report: dict[str, Any]) -> dict[str, Any]:
    capacity = report.get("capacity", {})
    metrics = report.get("metrics", {})
    checks = {
        "capacity_targets": bool(capacity.get("meets_targets")),
        "blind_isolation": metrics.get("blind_records_loaded") is False,
        "uncertainty": metrics.get("uncertainty", {})
        .get("headline", {})
        .get("at_10", {})
        .get("status")
        == "available",
        "failure_taxonomy": metrics.get("failure_taxonomy", {}).get("status") == "available",
    }
    return {
        "status": "partial" if all(checks.values()) else "fail",
        "evidence_checks": checks,
        "capacity": capacity,
        "stage_attribution": metrics.get("stage_attribution", {}),
        "note": (
            "Ranking misses are attributed; acquisition/projection/evidence still require "
            "journey traces."
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
        "note": "API state transitions pass; Android surface and worker scheduling remain separate gates.",
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
        "note": "Selection is complete; production remediation and blind one-shot evaluation are not.",
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


def build_report() -> dict[str, Any]:
    loaded = {name: _load(path) for name, path in ARTIFACTS.items()}
    missions = {
        "m1": {
            "artifact": _relative(ARTIFACTS["m1"]),
            "api_artifact": _relative(ARTIFACTS["m1_api"]),
            **_m1_gate(loaded["m1"]),
            "api_qualification": _m1_api_gate(loaded["m1_api"]),
        },
        "m2": {"artifact": _relative(ARTIFACTS["m2"]), **_m2_gate(loaded["m2"])},
        "m3": {"artifact": _relative(ARTIFACTS["m3"]), **_m3_gate(loaded["m3"])},
        "m4": {
            "artifact": _relative(ARTIFACTS["m4_android"]),
            **_m4_gate(loaded["m4_android"]),
        },
        "m5": {"artifact": _relative(ARTIFACTS["m5"]), **_m5_gate(loaded["m5"])},
        "m6": {"artifact": _relative(ARTIFACTS["m6"]), **_m6_gate(loaded["m6"])},
        "m7": {
            "artifact": _relative(ARTIFACTS["m7_backend"]),
            **_m7_gate(loaded["m7_backend"]),
        },
    }
    return {
        "report_version": REPORT_VERSION,
        "repository_sha": os.environ.get("GITHUB_SHA"),
        "status": "pre_field_release_candidate",
        "completion_gate_pass": False,
        "blind_read": False,
        "missions": missions,
        "unmet_gate_items": [
            "M1 Android/worker-backed journey for all 30 personas",
            (
                "M3 timeout/conditional-304/robots/source-identity qualification and "
                "observed-failure remediation"
            ),
            "M4 broad phone/tablet/a11y/error/offline qualification and release field validation",
            "M5 host-level disk-full and partial-write drill",
            "M6 production Top-3 remediation followed by one-shot blind evaluation",
            "M7 integrated Android clean-room install/upgrade/recovery and final field-readiness decision",
        ],
        "human_only_or_field_validation": [
            "live OAuth and real-user enrollment are excluded from automated clean-room evidence",
            "public HTTPS field validation is not replaced by local fixtures",
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
