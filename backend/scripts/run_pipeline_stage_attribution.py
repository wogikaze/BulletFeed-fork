"""Materialize earliest-stage attribution from a recorded pipeline trace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.evaluation.pipeline_attribution import (
    FULL_PIPELINE_STAGES,
    load_pipeline_trace,
)

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = (
    BACKEND
    / "tests"
    / "gold"
    / "m1_personas"
    / "v01"
    / "deterministic_baseline.json"
)
DEFAULT_OUTPUT = (
    BACKEND
    / "tests"
    / "gold"
    / "real_world_validation"
    / "v01"
    / "pipeline_stage_attribution.json"
)
M1_DEFAULT_TRACE_SCOPE = "m1_m7_deterministic_journey"


def _artifact_name(path: Path) -> str:
    try:
        return path.resolve().relative_to(BACKEND.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_trace_scope(path: Path) -> str | None:
    """Keep the legacy M1 default; custom traces must carry their own scope."""

    if path.resolve() == DEFAULT_TRACE.resolve():
        return M1_DEFAULT_TRACE_SCOPE
    return None


def _check(report: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    tenant_boundary = report["tenant_boundary"]
    if report["status"] != "available":
        violations.append("full pipeline stage coverage is unavailable")
    if report["coverage_status"] != "complete":
        violations.append("every trace must observe acquisition, projection, and evidence")
    if report["labels_loaded"] is not False:
        violations.append("labels were loaded")
    if report["ranking_inference_used"] is not False:
        violations.append("pipeline attribution inferred from ranking")
    if tenant_boundary["tenant_boundary_unknown_count"] > 0:
        violations.append("tenant boundary is unknown for one or more traces")
    if tenant_boundary["tenant_boundary_violation_count"] > 0:
        violations.append("tenant boundary violation observed")
    for stage in FULL_PIPELINE_STAGES:
        if report["coverage"][stage]["observed_trace_count"] == 0:
            violations.append(f"{stage} has no observed trace")
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    report = load_pipeline_trace(
        args.trace,
        source_artifact=_artifact_name(args.trace),
        trace_scope=_resolve_trace_scope(args.trace),
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if not args.check:
        return 0
    violations = _check(report)
    if violations:
        print("pipeline stage attribution check failed:", file=sys.stderr)
        print("\n".join(f"- {item}" for item in violations), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
