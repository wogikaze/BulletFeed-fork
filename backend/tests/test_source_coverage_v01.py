from __future__ import annotations

import json
import runpy
from pathlib import Path

from app.evaluation.source_coverage import (
    BENCHMARK_VERSION,
    INFORMATION_TYPES,
    SOURCE_FAMILIES,
    classify_case,
    coverage_release_violations,
    evaluate_source_coverage,
    load_source_coverage_gold,
    require_coverage_release_gate,
)
from app.services.source_registry import SourceRegistry

_V01 = Path(__file__).parent / "gold" / "source_coverage" / "v01"
_APP = Path(__file__).resolve().parents[1] / "app"
_LEAKAGE = Path(__file__).resolve().parents[1] / "scripts" / "check_source_coverage_gold_leakage.py"


def _corpus():
    return load_source_coverage_gold(_V01)


def test_corpus_covers_required_families_and_information_types() -> None:
    corpus = _corpus()
    manifest = json.loads((_V01 / "gold_manifest_v01.json").read_text(encoding="utf-8"))
    assert corpus.dataset_version == manifest["dataset_version"]
    assert set(INFORMATION_TYPES) <= corpus.information_types()
    assert set(SOURCE_FAMILIES) <= corpus.source_families()
    assert manifest["js_rendering_implemented"] is False
    for split in ("pilot", "blind"):
        scoped = corpus.for_split(split)
        assert set(INFORMATION_TYPES) <= scoped.information_types()
        assert set(SOURCE_FAMILIES) <= scoped.source_families()
        assert any(case.authority == "primary" and case.provenance for case in scoped.cases)
        assert any(case.js_required and case.source_family == "dynamic_web" for case in scoped.cases)


def test_pilot_and_blind_are_partitioned() -> None:
    corpus = _corpus()
    pilot = json.loads((_V01 / "pilot" / "index.json").read_text(encoding="utf-8"))
    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))
    assert set(pilot["case_ids"]).isdisjoint(holdout["case_ids"])
    assert set(pilot["urls"]).isdisjoint(holdout["urls"])
    assert {case.case_id for case in corpus.for_split("pilot").cases} == set(pilot["case_ids"])
    assert {case.case_id for case in corpus.for_split("blind").cases} == set(holdout["case_ids"])


def test_outcomes_distinguish_discovery_fetch_and_change_gaps() -> None:
    report = evaluate_source_coverage(_corpus(), split="pilot")
    outcomes = {row.outcome for row in report.cases}
    assert "covered" in outcomes
    assert "not_discovered" in outcomes
    assert "discovered_fetch_failed" in outcomes
    assert "fetched_change_missed" in outcomes
    assert "static_coverage_gap" in outcomes
    assert report.js_rendering_implemented is False
    assert report.static_coverage_gap_rate > 0
    assert report.by_source_family
    assert report.by_information_type
    assert report.by_topic


def test_js_required_pages_are_static_gaps_not_rendered() -> None:
    corpus = _corpus().for_split("pilot")
    registry = SourceRegistry()
    js_cases = [case for case in corpus.cases if case.js_required]
    assert js_cases
    for case in js_cases:
        outcome = classify_case(case, registry)
        assert outcome.outcome == "static_coverage_gap"
        assert outcome.acquired is False
        assert "64" in outcome.reason


def test_machine_readable_report_and_release_floors() -> None:
    report = evaluate_source_coverage(_corpus(), split="pilot")
    payload = report.as_dict()
    assert payload["benchmark_version"] == BENCHMARK_VERSION
    assert payload["js_rendering_implemented"] is False
    assert "discovery_recall" in payload
    assert "authoritative_source_precision" in payload
    assert "acquisition_success_rate" in payload
    assert "update_detection_recall" in payload
    assert "median_acquisition_delay_seconds" in payload
    assert "duplicate_source_rate" in payload
    require_coverage_release_gate(report)
    broken = evaluate_source_coverage(_corpus(), split="pilot")
    violations = coverage_release_violations(broken, floors={"discovery_recall": 1.01})
    assert violations


def test_blind_ids_are_not_hardcoded_in_production_app() -> None:
    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))
    forbidden = {
        "tests/gold/source_coverage/v01/blind",
        "gold/source_coverage/v01/blind",
        *holdout["case_ids"],
    }
    from app.evaluation.personalization_gold import scan_python_sources

    assert scan_python_sources(_APP, forbidden) == ()
    try:
        runpy.run_path(str(_LEAKAGE), run_name="__main__")
    except SystemExit as exc:
        assert exc.code in (0, None)
