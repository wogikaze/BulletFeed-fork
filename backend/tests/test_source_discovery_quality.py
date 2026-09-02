from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.source_discovery_quality import (
    DATASET_VERSION,
    classify_deterministic_probe,
    evaluate_source_discovery_quality,
    load_source_discovery_quality_corpus,
)

_ROOT = Path(__file__).parent / "gold" / "source_discovery" / "v02"
_CORPUS = _ROOT / "corpus.json"
_BASELINE_MEASUREMENT = _ROOT / "current_main_measurement.json"
_REMEDIATED_MEASUREMENT = _ROOT / "remediated_measurement.json"
_REMEDIATION_MEASUREMENT = _ROOT / "remediation_measurement.json"


def test_quality_corpus_is_dev_only_and_classifies_required_dimensions() -> None:
    corpus = load_source_discovery_quality_corpus(_CORPUS)
    assert corpus.dataset_version == DATASET_VERSION
    assert corpus.split == "dev"
    assert corpus.blind_read is False
    assert corpus.gold_injected is False
    assert corpus.human_gold is False
    assert corpus.hint_scope == "no_builtin_hints"
    assert {case.authority for case in corpus.cases} == {
        "primary",
        "secondary",
        "discovery_only",
    }
    assert "ja" in {case.language for case in corpus.cases}
    assert {classify_deterministic_probe(probe) for probe in corpus.probes} >= {
        "acquisition_failed",
        "extraction_failed",
    }
    assert corpus.live_qualification.included_in_metrics is False


def test_quality_measurement_reports_topic_family_and_failure_breakdowns() -> None:
    corpus = load_source_discovery_quality_corpus(_CORPUS)
    report = evaluate_source_discovery_quality(corpus)

    assert report.metrics["precision_at_20"] == 0.0
    assert report.metrics["primary_recall_at_20"] == 0.0
    assert report.metrics["japanese_recall_at_50"] == 0.0
    assert report.outcome_counts["undiscovered"] == 21
    assert report.failure_class_counts["acquisition_failed"] == 1
    assert report.failure_class_counts["extraction_failed"] == 1
    assert report.by_topic["React"]["primary_recall_at_20"] == 0.0
    assert report.by_family["rss_atom"]["recall_at_50"] == 0.0
    assert report.authority["discovery_only"]["recall_at_50"] == 0.0
    assert report.human_gold is False
    assert report.evaluation_status == "not_evaluable"
    assert "evaluation_not_evaluable:no_independent_hints" in report.violations
    assert report.live_qualification["included_in_metrics"] is False
    assert report.passed is False


def test_checked_in_remediated_measurement_matches_deterministic_replay() -> None:
    corpus = load_source_discovery_quality_corpus(_CORPUS)
    expected = json.loads(_REMEDIATED_MEASUREMENT.read_text(encoding="utf-8"))
    assert expected == evaluate_source_discovery_quality(
        corpus,
        source_sha=expected["source_sha"],
    ).as_dict()


def test_checked_in_baseline_measurement_preserves_observed_failures() -> None:
    baseline = json.loads(_BASELINE_MEASUREMENT.read_text(encoding="utf-8"))
    assert baseline["metrics"]["precision_at_20"] == 0.0
    assert baseline["by_topic"]["React"]["primary_recall_at_20"] == 0.0
    assert "evaluation_not_evaluable:no_independent_hints" in baseline["violations"]
    assert baseline["passed"] is False


def test_remediation_measurement_records_before_and_after() -> None:
    payload = json.loads(_REMEDIATION_MEASUREMENT.read_text(encoding="utf-8"))
    assert payload["baseline_status"] == "not_evaluable"
    assert payload["blind_read"] is False
    assert payload["gold_injected"] is False
    assert payload["before"]["metrics"]["precision_at_20"] == 0.0
    assert payload["after"]["metrics"]["precision_at_20"] == 0.0
    assert payload["before"]["evaluation_status"] == "not_evaluable"
    assert payload["after"]["evaluation_status"] == "not_evaluable"
    assert payload["after"]["passed"] is False


def test_probe_validation_is_keyed_by_probe_id() -> None:
    payload = json.loads(_CORPUS.read_text(encoding="utf-8"))
    payload["probes"][0]["expected_outcome"] = payload["probes"][1]["expected_outcome"]
    broken = _CORPUS.parent / "probe-order-break.json"
    try:
        broken.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="sdq-transport-http-503"):
            load_source_discovery_quality_corpus(broken)
    finally:
        broken.unlink(missing_ok=True)


def test_validator_rejects_lowered_quality_floor(tmp_path: Path) -> None:
    payload = json.loads(_CORPUS.read_text(encoding="utf-8"))
    payload["floors"]["precision_at_20"] = 0.79
    broken = tmp_path / "corpus.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="lowered"):
        load_source_discovery_quality_corpus(broken)
