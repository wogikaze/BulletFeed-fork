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
_MEASUREMENT = _ROOT / "current_main_measurement.json"


def test_quality_corpus_is_dev_only_and_classifies_required_dimensions() -> None:
    corpus = load_source_discovery_quality_corpus(_CORPUS)
    assert corpus.dataset_version == DATASET_VERSION
    assert corpus.split == "dev"
    assert corpus.blind_read is False
    assert corpus.gold_injected is False
    assert corpus.human_gold is False
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

    assert report.metrics["primary_recall_at_20"] >= 0.9
    assert report.metrics["japanese_recall_at_50"] >= 0.85
    assert report.outcome_counts["found_but_unsubscribable"] == 2
    assert report.outcome_counts["undiscovered"] == 1
    assert report.failure_class_counts["acquisition_failed"] == 1
    assert report.failure_class_counts["extraction_failed"] == 1
    assert report.by_topic["React"]["primary_recall_at_20"] < 0.7
    assert report.by_family["rss_atom"]["recall_at_50"] == 1.0
    assert report.authority["discovery_only"]["recall_at_50"] == 1.0
    assert report.live_qualification["included_in_metrics"] is False
    assert report.passed is False


def test_checked_in_main_measurement_matches_deterministic_replay() -> None:
    corpus = load_source_discovery_quality_corpus(_CORPUS)
    expected = json.loads(_MEASUREMENT.read_text(encoding="utf-8"))
    assert expected == evaluate_source_discovery_quality(corpus).as_dict()


def test_validator_rejects_lowered_quality_floor(tmp_path: Path) -> None:
    payload = json.loads(_CORPUS.read_text(encoding="utf-8"))
    payload["floors"]["precision_at_20"] = 0.79
    broken = tmp_path / "corpus.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="lowered"):
        load_source_discovery_quality_corpus(broken)
