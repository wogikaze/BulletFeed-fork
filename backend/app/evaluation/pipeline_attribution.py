"""Attribute failures from explicit, tenant-scoped pipeline traces.

This module consumes harness traces only.  It does not load validation labels,
and it never turns a ranking result into an acquisition, projection, or
evidence failure.  Missing or combined stages remain uncovered instead of
being guessed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ATTRIBUTION_VERSION = "pipeline-stage-attribution-v1"
FULL_PIPELINE_STAGES = ("acquisition", "projection", "evidence")
RANKING_STAGE = "ranking"
KNOWN_STAGES = (*FULL_PIPELINE_STAGES, RANKING_STAGE)
UNATTRIBUTED_STAGE = "unattributed"


def attribute_pipeline_trace(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    source_artifact: str | None = None,
    source_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Build an attribution artifact from explicit stage observations.

    The input may be a report with ``reports``/``traces``, or one trace with a
    top-level ``stages`` list.  Only exact stage names in ``KNOWN_STAGES`` are
    attributed.  A missing stage, ``feed`` stage, or combined
    ``acquisition_projection`` stage is not treated as evidence about an
    individual pipeline stage.
    """

    if source_artifact is not None and _contains_blind_path(source_artifact):
        raise ValueError("blind trace artifacts are not allowed")
    rows, root = _trace_rows(payload)
    _assert_not_blind(root, rows)
    if source_artifact_sha256 is not None and not _is_sha256(source_artifact_sha256):
        raise ValueError("source_artifact_sha256 must be a 64-character hex digest")

    trace_results: list[dict[str, Any]] = []
    seen_trace_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        trace_id = _trace_id(row, root=root, index=index)
        if trace_id in seen_trace_ids:
            raise ValueError(f"duplicate trace_id: {trace_id}")
        seen_trace_ids.add(trace_id)
        tenant_id, tenant_identity_source = _tenant_id(row, trace_id)
        observations = _stage_observations(row.get("stages"), trace_id=trace_id)
        observed_names = tuple(name for name, _ok, _detail, _metrics in observations)
        observed_set = set(observed_names)
        failed_names = {
            name for name, ok, _detail, _metrics in observations if not ok
        }
        failed_stages = tuple(stage for stage in KNOWN_STAGES if stage in failed_names)
        unattributed_failed_stages = tuple(
            name
            for name in observed_names
            if name not in KNOWN_STAGES and name in failed_names
        )
        earliest = next(
            (stage for stage in KNOWN_STAGES if stage in failed_names),
            None,
        )
        if earliest in FULL_PIPELINE_STAGES:
            failure_scope = "full_pipeline"
        elif earliest == RANKING_STAGE:
            failure_scope = "ranking"
        elif unattributed_failed_stages:
            failure_scope = UNATTRIBUTED_STAGE
        else:
            failure_scope = None

        tenant_checks = [
            ok
            for name, ok, _detail, _metrics in observations
            if name == "tenant_isolation"
        ]
        if isinstance(row.get("tenant_leak"), bool):
            tenant_checks.append(not row["tenant_leak"])
        tenant_boundary_ok = all(tenant_checks) if tenant_checks else None
        stage_observations = {
            name: {
                "ok": ok,
                "detail": detail,
                "metrics": metrics,
            }
            for name, ok, detail, metrics in observations
            if name in (*KNOWN_STAGES, "tenant_isolation")
        }
        trace_results.append(
            {
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "tenant_identity_source": tenant_identity_source,
                "observed_stages": list(observed_names),
                "observed_pipeline_stages": [
                    stage for stage in FULL_PIPELINE_STAGES if stage in observed_set
                ],
                "missing_pipeline_stages": [
                    stage for stage in FULL_PIPELINE_STAGES if stage not in observed_set
                ],
                "failed_stages": list(failed_stages),
                "unattributed_failed_stages": list(unattributed_failed_stages),
                "earliest_observed_failure": earliest,
                "failure_scope": failure_scope,
                "stage_observations": stage_observations,
                "tenant_boundary_ok": tenant_boundary_ok,
            }
        )

    trace_count = len(trace_results)
    observed_counts = Counter(
        stage
        for result in trace_results
        for stage in result["observed_stages"]
        if stage in KNOWN_STAGES
    )
    failed_counts = Counter(
        stage
        for result in trace_results
        for stage in result["failed_stages"]
    )
    unattributed_counts = Counter(
        stage
        for result in trace_results
        for stage in result["unattributed_failed_stages"]
    )
    earliest_counts: Counter[str] = Counter()
    for result in trace_results:
        earliest = result["earliest_observed_failure"]
        if earliest is not None:
            earliest_counts[earliest] += 1
        elif result["unattributed_failed_stages"]:
            earliest_counts[UNATTRIBUTED_STAGE] += 1
        else:
            earliest_counts["ok"] += 1

    coverage = {
        stage: {
            "observed_trace_count": sum(
                stage in result["observed_stages"] for result in trace_results
            ),
            "failure_trace_count": sum(
                stage in result["failed_stages"] for result in trace_results
            ),
            "missing_trace_count": sum(
                stage not in result["observed_stages"] for result in trace_results
            ),
        }
        for stage in FULL_PIPELINE_STAGES
    }
    complete_trace_count = sum(
        not result["missing_pipeline_stages"] for result in trace_results
    )
    if not trace_results:
        status = "not_available"
        coverage_status = "not_available"
    elif all(row["observed_trace_count"] > 0 for row in coverage.values()):
        status = "available"
        coverage_status = "complete" if complete_trace_count == trace_count else "partial"
    else:
        status = "partial"
        coverage_status = "partial"

    tenant_ids = {result["tenant_id"] for result in trace_results}
    tenant_boundary_violations = sum(
        result["tenant_boundary_ok"] is False for result in trace_results
    )
    provenance = {
        "source_artifact": source_artifact,
        "source_artifact_sha256": source_artifact_sha256,
        "trace_version": root.get("trace_version"),
        "harness_version": root.get("harness_version")
        or root.get("acceptance_version"),
        "mode": root.get("mode"),
        "repository_sha": root.get("repository_sha"),
        "label_source": root.get("label_source"),
    }
    return {
        "attribution_version": ATTRIBUTION_VERSION,
        "status": status,
        "coverage_status": coverage_status,
        "attribution_basis": "explicit stage ok flags only",
        "labels_loaded": False,
        "ranking_inference_used": False,
        "trace_count": trace_count,
        "complete_trace_count": complete_trace_count,
        "provenance": provenance,
        "tenant_boundary": {
            "mode": "trace_local",
            "cross_tenant_joins": False,
            "trace_count": trace_count,
            "unique_tenant_count": len(tenant_ids),
            "tenant_boundary_unknown_count": sum(
                result["tenant_boundary_ok"] is None for result in trace_results
            ),
            "tenant_boundary_violation_count": tenant_boundary_violations,
        },
        "coverage": coverage,
        "observed_stage_counts": {
            stage: observed_counts[stage] for stage in KNOWN_STAGES
        },
        "failure_counts": {
            stage: failed_counts[stage] for stage in KNOWN_STAGES
        }
        | {UNATTRIBUTED_STAGE: sum(unattributed_counts.values())},
        "unattributed_failure_stages": dict(sorted(unattributed_counts.items())),
        "earliest_failure_counts": {
            stage: earliest_counts[stage] for stage in (*KNOWN_STAGES, UNATTRIBUTED_STAGE, "ok")
        },
        "traces": trace_results,
    }


def load_pipeline_trace(
    path: Path,
    *,
    source_artifact: str | None = None,
) -> dict[str, Any]:
    """Load one non-blind trace artifact and return its attribution."""

    path = Path(path)
    if _contains_blind_path(path):
        raise ValueError("blind trace artifacts are not allowed")
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return attribute_pipeline_trace(
        payload,
        source_artifact=source_artifact or path.as_posix(),
        source_artifact_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _trace_rows(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> tuple[tuple[Mapping[str, Any], ...], Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        root = payload
        rows: Any = payload.get("traces")
        if rows is None:
            rows = payload.get("reports")
        if rows is None and "stages" in payload:
            rows = [payload]
    else:
        root = {}
        rows = payload
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("pipeline trace must contain a traces/reports array or stages")
    normalized: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"trace {index} must be a JSON object")
        normalized.append(row)
    return tuple(normalized), root


def _assert_not_blind(root: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    if root.get("split") == "blind":
        raise ValueError("blind trace records are not allowed")
    if root.get("blind_records_loaded") is True or root.get("blind_read") is True:
        raise ValueError("trace claims blind records were loaded")
    if any(row.get("split") == "blind" for row in rows):
        raise ValueError("blind trace records are not allowed")


def _stage_observations(
    stages: Any,
    *,
    trace_id: str,
) -> tuple[tuple[str, bool, str, dict[str, Any]], ...]:
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes, bytearray)):
        raise ValueError(f"trace {trace_id} stages must be an array")
    seen: set[str] = set()
    observations: list[tuple[str, bool, str, dict[str, Any]]] = []
    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, Mapping):
            raise ValueError(f"trace {trace_id} stage {index} must be an object")
        name = stage.get("stage")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"trace {trace_id} stage {index} has no name")
        if name in seen:
            raise ValueError(f"trace {trace_id} repeats stage {name}")
        seen.add(name)
        ok = stage.get("ok")
        if not isinstance(ok, bool):
            raise ValueError(f"trace {trace_id} stage {name} ok must be boolean")
        detail = stage.get("detail", "")
        if detail is None:
            detail = ""
        if not isinstance(detail, str):
            raise ValueError(f"trace {trace_id} stage {name} detail must be a string")
        metrics = stage.get("metrics", {})
        if metrics is None:
            metrics = {}
        if not isinstance(metrics, Mapping):
            raise ValueError(f"trace {trace_id} stage {name} metrics must be an object")
        observations.append((name, ok, detail, dict(metrics)))
    return tuple(observations)


def _trace_id(
    row: Mapping[str, Any],
    *,
    root: Mapping[str, Any],
    index: int,
) -> str:
    for key in ("trace_id", "persona_id", "case_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    root_id = root.get("trace_id")
    if isinstance(root_id, str) and root_id.strip() and index == 1:
        return root_id
    return f"trace-{index}"


def _tenant_id(row: Mapping[str, Any], trace_id: str) -> tuple[str, str]:
    for key in ("tenant_id", "user_id", "persona_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value, key
    return trace_id, "trace_id"


def _contains_blind_path(path: str | Path) -> bool:
    return any(part.casefold() == "blind" for part in Path(path).parts)


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
