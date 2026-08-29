from pathlib import Path

from app.evaluation.e2e_unknown_recall import (
    evaluate_e2e_unknown_recall,
    load_e2e_cases,
    require_e2e_release_gate,
)

_PILOT = Path(__file__).parent / "gold/e2e_unknown_recall/v01/pilot/cases.json"
_BLIND = Path(__file__).parent / "gold/e2e_unknown_recall/v01/blind/cases.json"
_PRODUCTION_MODULE = Path(__file__).parents[1] / "app/evaluation/e2e_unknown_recall.py"


def test_pilot_e2e_has_both_cohorts_and_stage_attribution() -> None:
    cases = load_e2e_cases(_PILOT)
    report = evaluate_e2e_unknown_recall(cases)
    require_e2e_release_gate(report)
    assert report.by_cohort["cold_start"].case_count >= 1
    assert report.by_cohort["history_rich"].case_count >= 1
    assert report.overall.unknown_but_hidden == 0
    assert report.overall.false_merge_misses == 0
    stages = {row.case_id: row.stage for row in report.cases}
    assert stages["e2e-p-001"] == "ok"
    assert stages["e2e-p-003"] == "ok"
    assert stages["e2e-p-004"] == "ok"
    assert stages["e2e-p-005"] == "ok"
    assert stages["e2e-p-006"] == "discovery"
    hidden = next(row for row in report.cases if row.case_id == "e2e-p-003")
    assert hidden.suppression == "hide"
    assert hidden.surfaced is False
    uncertain = next(row for row in report.cases if row.case_id == "e2e-p-005")
    assert uncertain.suppression != "hide"
    assert uncertain.surfaced is True


def test_aggregate_cannot_hide_unknown_but_hidden() -> None:
    cases = load_e2e_cases(_PILOT)
    report = evaluate_e2e_unknown_recall(cases)
    assert "unknown_but_hidden" in report.catastrophic
    assert report.catastrophic["unknown_but_hidden"] == 0
    assert report.overall.important_unknown_recall >= 0.7


def test_blind_split_is_evaluation_only_and_still_gated() -> None:
    report = evaluate_e2e_unknown_recall(load_e2e_cases(_BLIND))
    require_e2e_release_gate(report, require_recall=False)
    assert {row.case_id for row in report.cases} == {
        "e2e-b-001",
        "e2e-b-002",
        "e2e-b-003",
        "e2e-b-004",
    }
    stages = {row.case_id: row.stage for row in report.cases}
    assert stages["e2e-b-003"] == "fetch"


def test_production_module_does_not_name_blind_path() -> None:
    text = _PRODUCTION_MODULE.read_text(encoding="utf-8")
    assert "e2e_unknown_recall/v01/blind" not in text
    assert "e2e-b-" not in text
