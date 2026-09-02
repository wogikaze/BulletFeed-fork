import json
from pathlib import Path

import pytest

from app.evaluation.pipeline_attribution import (
    FULL_PIPELINE_STAGES,
    attribute_pipeline_trace,
    load_pipeline_trace,
)

_M1_TRACE = Path(__file__).parent / "gold" / "m1_personas" / "v01" / "deterministic_baseline.json"
_CLEAN_ROOM_TRACE = Path(__file__).parent / "gold" / "clean_room" / "v01" / "backend_report.json"


def _payload(*traces: dict) -> dict:
    return {
        "trace_version": "pipeline-stage-trace-v1",
        "harness_version": "test-harness-v1",
        "mode": "deterministic_fixture",
        "label_source": "constructed",
        "traces": list(traces),
    }


def _trace(trace_id: str, stages: list[dict], *, tenant_id: str | None = None) -> dict:
    row = {"trace_id": trace_id, "stages": stages}
    if tenant_id is not None:
        row["tenant_id"] = tenant_id
    return row


def _stage(name: str, ok: bool, detail: str = "") -> dict:
    return {"stage": name, "ok": ok, "detail": detail, "metrics": {}}


def test_attributes_the_earliest_explicit_pipeline_failure() -> None:
    report = attribute_pipeline_trace(
        _payload(
            _trace(
                "acquisition-failure",
                [
                    _stage("acquisition", False, "worker failed"),
                    _stage("projection", False, "not reached"),
                    _stage("evidence", False, "not reached"),
                    _stage("tenant_isolation", True),
                ],
                tenant_id="tenant-a",
            ),
            _trace(
                "projection-failure",
                [
                    _stage("acquisition", True),
                    _stage("projection", False, "feed row missing"),
                    _stage("evidence", False, "not reached"),
                    _stage("tenant_isolation", True),
                ],
                tenant_id="tenant-b",
            ),
            _trace(
                "evidence-failure",
                [
                    _stage("acquisition", True),
                    _stage("projection", True),
                    _stage("evidence", False, "claim evidence missing"),
                    _stage("tenant_isolation", True),
                ],
                tenant_id="tenant-c",
            ),
        )
    )

    assert report["status"] == "available"
    assert report["coverage_status"] == "complete"
    assert report["earliest_failure_counts"] == {
        "acquisition": 1,
        "projection": 1,
        "evidence": 1,
        "ranking": 0,
        "unattributed": 0,
        "ok": 0,
    }
    assert report["failure_counts"] == {
        "acquisition": 1,
        "projection": 2,
        "evidence": 3,
        "ranking": 0,
        "unattributed": 0,
    }
    assert [row["earliest_observed_failure"] for row in report["traces"]] == [
        "acquisition",
        "projection",
        "evidence",
    ]
    assert report["tenant_boundary"] == {
        "mode": "trace_local",
        "cross_tenant_joins": False,
        "trace_count": 3,
        "unique_tenant_count": 3,
        "tenant_boundary_unknown_count": 0,
        "tenant_boundary_violation_count": 0,
    }


def test_combined_or_unrecognized_stages_are_not_split_or_inferred() -> None:
    report = attribute_pipeline_trace(
        _payload(
            _trace(
                "clean-room",
                [
                    _stage("acquisition_projection", False, "seed endpoint failed"),
                    _stage("feed", False, "no cards"),
                ],
            )
        )
    )

    result = report["traces"][0]
    assert result["earliest_observed_failure"] is None
    assert result["failed_stages"] == []
    assert result["unattributed_failed_stages"] == ["acquisition_projection", "feed"]
    assert report["failure_counts"]["acquisition"] == 0
    assert report["failure_counts"]["projection"] == 0
    assert report["failure_counts"]["evidence"] == 0
    assert report["failure_counts"]["unattributed"] == 2
    assert report["earliest_failure_counts"]["unattributed"] == 1


def test_ranking_trace_stays_ranking_only() -> None:
    report = attribute_pipeline_trace(
        _payload(
            _trace(
                "ranking-replay",
                [_stage("ranking", False, "ranked outside top ten")],
            )
        )
    )

    result = report["traces"][0]
    assert result["earliest_observed_failure"] == "ranking"
    assert result["failure_scope"] == "ranking"
    assert report["failure_counts"]["ranking"] == 1
    assert all(report["failure_counts"][stage] == 0 for stage in FULL_PIPELINE_STAGES)
    assert all(
        report["coverage"][stage]["observed_trace_count"] == 0
        for stage in FULL_PIPELINE_STAGES
    )
    assert report["ranking_inference_used"] is False


@pytest.mark.parametrize(
    ("trace", "message"),
    [
        (
            _trace(
                "tenant-leak",
                [_stage("tenant_isolation", True)],
            )
            | {"tenant_leak": True},
            "tenant boundary violation",
        ),
        (
            _trace("tenant-unknown", [_stage("acquisition", True)]),
            "tenant boundary is unknown",
        ),
    ],
)
def test_tenant_boundary_problems_invalidate_attribution(
    trace: dict, message: str
) -> None:
    report = attribute_pipeline_trace(_payload(trace))

    assert report["status"] == "invalid"
    assert report["coverage_status"] == "invalid"
    assert report["tenant_boundary"]["tenant_boundary_unknown_count"] == (
        1 if message.endswith("unknown") else 0
    )
    assert report["tenant_boundary"]["tenant_boundary_violation_count"] == (
        1 if message.endswith("violation") else 0
    )


@pytest.mark.parametrize(
    "marker",
    [
        {"human_gold": True},
        {"label_source": "human"},
        {"evaluation_label": "constructed"},
    ],
)
def test_human_or_arbitrary_label_markers_are_rejected(marker: dict) -> None:
    with pytest.raises(ValueError, match="label"):
        attribute_pipeline_trace(_payload(_trace("labeled", [_stage("ranking", True)])) | marker)


def test_existing_m1_trace_has_full_pipeline_coverage_without_labels() -> None:
    report = load_pipeline_trace(_M1_TRACE)

    assert report["status"] == "available"
    assert report["coverage_status"] == "complete"
    assert report["trace_count"] == 30
    assert report["complete_trace_count"] == 30
    assert report["labels_loaded"] is False
    assert report["ranking_inference_used"] is False
    assert report["provenance"]["harness_version"] == "m1-zero-to-useful-v02"
    assert all(
        report["coverage"][stage]["observed_trace_count"] == 30
        for stage in FULL_PIPELINE_STAGES
    )


def test_clean_room_trace_uses_the_split_pipeline_stages() -> None:
    report = load_pipeline_trace(_CLEAN_ROOM_TRACE)

    assert report["status"] == "invalid"
    assert report["coverage_status"] == "invalid"
    assert report["trace_count"] == 1
    assert report["provenance"]["harness_version"] == "m7-clean-room-backend-v1"
    assert report["traces"][0]["trace_id"] == "m7-clean-room"
    assert report["tenant_boundary"]["tenant_boundary_unknown_count"] == 1
    assert report["tenant_boundary"]["cross_tenant_joins"] is False


def test_blind_trace_path_is_rejected_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "blind" / "trace.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"stages": []}), encoding="utf-8")

    def fail_read(_self: Path, *args, **kwargs):
        raise AssertionError("blind trace was read")

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(ValueError, match="blind"):
        load_pipeline_trace(path)


def test_blind_split_is_rejected_for_direct_payload() -> None:
    with pytest.raises(ValueError, match="blind"):
        attribute_pipeline_trace(
            {
                "split": "blind",
                "traces": [_trace("holdout", [_stage("acquisition", False)])],
            }
        )
