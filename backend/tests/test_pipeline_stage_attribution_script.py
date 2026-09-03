import json
from pathlib import Path

from scripts.run_pipeline_stage_attribution import (
    DEFAULT_TRACE,
    M1_DEFAULT_TRACE_SCOPE,
    _resolve_trace_scope,
    main,
)


def _stage(name: str) -> dict:
    return {"stage": name, "ok": True, "detail": "", "metrics": {}}


def test_default_trace_keeps_legacy_m1_m7_scope() -> None:
    assert _resolve_trace_scope(DEFAULT_TRACE) == M1_DEFAULT_TRACE_SCOPE


def test_custom_m2_trace_preserves_embedded_scope(tmp_path: Path) -> None:
    trace = tmp_path / "m2_historical_trace.json"
    output = tmp_path / "attribution.json"
    trace.write_text(
        json.dumps(
            {
                "trace_scope": "m2_historical_corpus",
                "dataset_version": "real-world-validation-v0.2",
                "harness_version": "m2-harness-v1",
                "label_source": "no-label",
                "traces": [
                    {
                        "trace_id": "m2-1",
                        "tenant_id": "tenant-a",
                        "stages": [
                            _stage("acquisition"),
                            _stage("projection"),
                            _stage("evidence"),
                            _stage("tenant_isolation"),
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _resolve_trace_scope(trace) is None
    assert main(["--trace", str(trace), "--output", str(output), "--check"]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "available"
    assert report["coverage_status"] == "complete"
    assert report["provenance"]["trace_scope"] == "m2_historical_corpus"
    assert report["provenance"]["dataset_version"] == "real-world-validation-v0.2"
    assert report["provenance"]["harness_version"] == "m2-harness-v1"


def test_custom_trace_without_scope_does_not_gain_m2_scope(tmp_path: Path) -> None:
    trace = tmp_path / "generated.json"

    assert _resolve_trace_scope(trace) is None
