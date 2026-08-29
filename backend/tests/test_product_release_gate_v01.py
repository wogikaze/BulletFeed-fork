import json
from pathlib import Path

from app.evaluation.product_release_gate import (
    evaluate_product_release_gate,
    floors_version_fingerprint,
    load_product_release_floors,
    require_product_release_gate,
)

_FLOORS = Path(__file__).parent / "gold/product_release/v01/floors.json"
_E2E = Path(__file__).parent / "gold/e2e_unknown_recall/v01/pilot/cases.json"
_KNOWNNESS = Path(__file__).parent / "gold/knownness/v01"
_COVERAGE = Path(__file__).parent / "gold/source_coverage/v01"


def _report(**overrides):
    floors = load_product_release_floors(_FLOORS)
    if overrides:
        floors = floors.model_copy(update=overrides)
    return evaluate_product_release_gate(
        floors=floors,
        e2e_cases_path=_E2E,
        knownness_dir=_KNOWNNESS,
        coverage_dir=_COVERAGE,
    )


def test_versioned_floors_pass_current_pilot_stack() -> None:
    floors = load_product_release_floors(_FLOORS)
    assert floors.version == "product-release-floors-v1"
    assert "hard gate" in floors.reason
    report = _report()
    require_product_release_gate(report)
    assert report.hard_failures == ()
    assert report.observations["unknown_but_hidden"] == 0
    assert report.observations["false_merge_misses"] == 0
    assert (
        report.observations["cold_start_important_unknown_recall"]
        >= floors.cold_start.important_unknown_recall
    )
    assert (
        report.observations["history_rich_important_unknown_recall"]
        >= floors.history_rich.important_unknown_recall
    )


def test_soft_recall_failure_is_not_a_hard_gate() -> None:
    report = _report(important_unknown_recall=0.99)
    assert report.findings
    assert "important_unknown_recall" in {item.metric for item in report.findings}
    assert report.hard_failures == ()


def test_floor_file_changes_require_new_version_reason() -> None:
    payload = json.loads(_FLOORS.read_text(encoding="utf-8"))
    fingerprint = floors_version_fingerprint(_FLOORS)
    assert payload["version"] in fingerprint
    assert payload["reason"] in fingerprint


def test_production_module_does_not_load_blind_paths() -> None:
    text = Path("app/evaluation/product_release_gate.py").read_text(encoding="utf-8")
    assert "blind" not in text
