"""Write a machine-readable M2 corpus and evaluation readiness report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.evaluation.m2_validation_metrics import evaluate_m2_production_scoring
from app.evaluation.pipeline_attribution import load_pipeline_trace
from app.evaluation.real_world_validation import (
    CONTRACT_VERSION,
    DATASET_VERSION,
    capacity_status,
    coverage_inventory,
    load_real_world_validation,
    load_real_world_validation_for_production_scoring,
)

BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND / "tests" / "gold" / "real_world_validation" / "v01"
PIPELINE_TRACE = (
    BACKEND / "tests" / "gold" / "m1_personas" / "v01" / "deterministic_baseline.json"
)


def _git_sha() -> str | None:
    return os.environ.get("GITHUB_SHA")


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows).items()))


def _relative_backend_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BACKEND.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_report(*, pipeline_trace: Path = PIPELINE_TRACE) -> dict[str, Any]:
    corpus = load_real_world_validation(CORPUS)
    status = capacity_status(corpus)
    production = load_real_world_validation_for_production_scoring(CORPUS)
    trace_scope = (
        "m1_m7_deterministic_journey"
        if pipeline_trace.resolve() == PIPELINE_TRACE.resolve()
        else None
    )
    pipeline_attribution = load_pipeline_trace(
        pipeline_trace,
        source_artifact=_relative_backend_path(pipeline_trace),
        trace_scope=trace_scope,
    )
    report = {
        "report_version": "m2-corpus-readiness-v1",
        "dataset_version": DATASET_VERSION,
        "contract_version": CONTRACT_VERSION,
        "frozen_main_sha": _git_sha(),
        "capacity": asdict(status),
        "coverage": coverage_inventory(corpus),
        "production_scoring": {
            "splits": sorted(production.indexes),
            "blind_records_loaded": False,
        },
        "pipeline_attribution": pipeline_attribution,
        "splits": {},
        "judgments": {
            "label_source": "AI-silver",
            "human_gold": False,
            "by_stratum": _counts(
                [
                    row.model_dump()
                    for row in corpus.judgments
                    if row.split != "blind"
                ],
                "stratum",
            ),
        },
        "metrics": evaluate_m2_production_scoring(production),
    }
    for split in ("pilot", "dev", "blind"):
        scoped = corpus.for_split(split)
        report["splits"][split] = {
            "events": len(scoped.events),
            "real_events": len(scoped.real_events()),
            "sources": len(scoped.sources),
            "profiles": len(scoped.profiles),
            "judgments": len(scoped.judgments),
            "source_families": sorted({row.source_family for row in scoped.sources}),
            "languages": sorted({row.language for row in scoped.sources}),
            "persona_templates": sorted({row.persona_template for row in scoped.profiles}),
        }
    return report


def _check_report(report: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    capacity = report["capacity"]
    if not capacity["meets_targets"]:
        violations.extend(str(item) for item in capacity["missing"])
    if not report["frozen_main_sha"]:
        violations.append("frozen_main_sha is missing")
    metrics = report["metrics"]
    if metrics["blind_records_loaded"]:
        violations.append("production metrics loaded blind records")
    if metrics["sample"]["judgment_count"] < 10_000:
        violations.append("production metrics have fewer than 10,000 judgments")
    if metrics["uncertainty"]["headline"]["at_10"]["status"] != "available":
        violations.append("headline at_10 uncertainty is unavailable")
    if metrics["failure_taxonomy"]["status"] != "available":
        violations.append("failure taxonomy is unavailable")
    pipeline = report.get("pipeline_attribution", {})
    if pipeline.get("status") != "available":
        violations.append("pipeline stage trace integrity is unavailable")
    if pipeline.get("coverage_status") != "complete":
        violations.append("pipeline stage trace coverage is incomplete")
    if pipeline.get("labels_loaded") is not False:
        violations.append("pipeline attribution loaded labels")
    if pipeline.get("ranking_inference_used") is not False:
        violations.append("pipeline attribution inferred failures from ranking")
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--pipeline-trace", type=Path, default=PIPELINE_TRACE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(pipeline_trace=args.pipeline_trace)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if not args.check:
        return 0
    violations = _check_report(report)
    if violations:
        print("M2 validation report gate failed:", file=sys.stderr)
        print("\n".join(f"- {item}" for item in violations), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
