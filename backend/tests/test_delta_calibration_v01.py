from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.delta_adversarial_gold import load_delta_adversarial_gold, scan_python_sources
from app.evaluation.delta_calibration import (
    BENCHMARK_VERSION,
    FALSE_MERGE_RATE_FLOOR,
    FALSE_SPLIT_RATE_FLOOR,
    calibration_release_violations,
    default_algorithm_score,
    evaluate_calibration,
    load_calibration_gold,
    require_calibration_release_gate,
    select_thresholds,
)
from app.services.delta_thresholds import (
    FALSE_MERGE_COST,
    FALSE_SPLIT_COST,
    calibrated_knownness_may_hide,
    calibrated_knownness_visibility,
    calibrated_thresholds,
    decision_cost,
)
from app.services.knowledge_identity import KnowledgeIdentityDecision, compare_knowledge_identity

_GOLD = Path(__file__).parent / "gold" / "delta_adversarial" / "v01"
_CAL = Path(__file__).parent / "gold" / "delta_calibration" / "v01"
_APP = Path(__file__).resolve().parents[1] / "app"


def _corpus():
    return load_calibration_gold(_GOLD)


def test_false_merge_costs_more_than_false_split() -> None:
    assert FALSE_MERGE_COST > FALSE_SPLIT_COST
    assert decision_cost(false_merge_count=1, false_split_count=0, uncertain_count=0) > decision_cost(
        false_merge_count=0,
        false_split_count=3,
        uncertain_count=0,
    )
    assert FALSE_MERGE_RATE_FLOOR < FALSE_SPLIT_RATE_FLOOR


def test_selection_uses_pilot_cost_not_accuracy_or_blind_labels() -> None:
    corpus = _corpus()
    thresholds, selected, accuracy_max = select_thresholds(corpus)
    assert thresholds.selection_split == "pilot"
    assert selected.cost <= accuracy_max.cost
    assert selected.false_merge_count <= accuracy_max.false_merge_count or selected.cost < accuracy_max.cost
    report = evaluate_calibration(
        corpus,
        split="pilot",
        thresholds=thresholds,
        selected=selected,
        accuracy_maximizer=accuracy_max,
    )
    assert report.selected_by == "asymmetric_cost"
    assert report.labels_rewritten is False
    assert report.replay["selection_split"] == "pilot"
    if selected.equivalent_overlap != accuracy_max.equivalent_overlap:
        assert selected.accuracy <= accuracy_max.accuracy


def test_gold_labels_are_not_rewritten() -> None:
    before = (_GOLD / "pilot" / "cases.json").read_bytes()
    evaluate_calibration(_corpus(), split="pilot")
    assert (_GOLD / "pilot" / "cases.json").read_bytes() == before
    assert load_delta_adversarial_gold(_GOLD).cases == _corpus().cases


def test_blind_evaluation_reports_reliability_and_stricter_merge_floor() -> None:
    corpus = _corpus()
    thresholds, selected, accuracy_max = select_thresholds(corpus)
    blind = evaluate_calibration(
        corpus,
        split="blind",
        thresholds=thresholds,
        selected=selected,
        accuracy_maximizer=accuracy_max,
    )
    assert blind.split == "blind"
    assert {row.family for row in blind.families} == {"equivalence", "coreference"}
    for family in blind.families:
        assert family.reliability
        assert family.pair_count == len(corpus.for_split("blind").cases)
    require_calibration_release_gate(blind)
    assert calibration_release_violations(blind) == ()


def test_low_confidence_abstains_instead_of_forced_merge() -> None:
    from app.evaluation.delta_calibration import predict_case

    corpus = _corpus().for_split("pilot")
    thresholds = calibrated_thresholds()
    saw_uncertain = False
    for case in corpus.cases:
        _prediction, label, confidence, abstained = predict_case(case, thresholds)
        if confidence == "low" or abstained:
            assert label == "uncertain" or not _prediction.same_event
            saw_uncertain = True
        if label == "uncertain":
            assert _prediction.same_event is False
    assert saw_uncertain or any(case.equivalence == "uncertain" for case in corpus.cases)


def test_knownness_consumes_calibrated_confidence() -> None:
    thresholds = calibrated_thresholds()
    uncertain = KnowledgeIdentityDecision(
        "uncertain",
        "ambiguous",
        "low",
        thresholds.replay_version,
        "a",
        "b",
        None,
    )
    same_high = KnowledgeIdentityDecision(
        "same_target",
        "equivalent restatement",
        "high",
        thresholds.replay_version,
        "a",
        "b",
        "a",
    )
    assert calibrated_knownness_may_hide(uncertain) is False
    assert calibrated_knownness_visibility(uncertain, "hide") == "show"
    assert calibrated_knownness_may_hide(same_high) is True

    decision = compare_knowledge_identity(
        "React 19 released",
        "facebook/react tagged v19",
        "React 19 is out",
        "facebook/react published v19",
        policy=thresholds.equivalence_policy(),
    )
    if decision.confidence == "low" or decision.label == "uncertain":
        assert calibrated_knownness_may_hide(decision) is False


def test_checked_in_report_is_machine_readable() -> None:
    baseline = json.loads((_CAL / "pilot_baseline.json").read_text(encoding="utf-8"))
    stored = json.loads((_CAL / "thresholds.json").read_text(encoding="utf-8"))
    assert baseline["benchmark_version"] == BENCHMARK_VERSION
    assert baseline["selected_by"] == "asymmetric_cost"
    assert baseline["labels_rewritten"] is False
    assert stored["false_merge_cost"] > stored["false_split_cost"]
    assert stored["selection_split"] == "pilot"
    assert stored["replay_version"]


def test_default_algorithm_is_not_retuned_against_gold() -> None:
    from app.services.claim_semantics import DEFAULT_EQUIVALENCE_POLICY

    diagnostic = default_algorithm_score(_corpus(), split="pilot")
    selected = calibrated_thresholds()
    assert DEFAULT_EQUIVALENCE_POLICY.equivalent_overlap != selected.equivalent_overlap or (
        diagnostic.equivalent_overlap == DEFAULT_EQUIVALENCE_POLICY.equivalent_overlap
    )
    assert DEFAULT_EQUIVALENCE_POLICY.version == "semantic-equivalence-v1"


def test_blind_ids_are_not_hardcoded_in_production_app() -> None:
    holdout = json.loads((_GOLD / "blind" / "index.json").read_text(encoding="utf-8"))
    forbidden = {
        *holdout["case_ids"],
        *holdout["bundle_ids"],
        *holdout["event_ids"],
    }
    assert scan_python_sources(_APP, forbidden) == ()


def test_gate_rejects_accuracy_objective() -> None:
    from dataclasses import replace

    report = evaluate_calibration(_corpus(), split="pilot")
    mutated = replace(report, selected_by="accuracy")
    with pytest.raises(AssertionError, match="asymmetric cost"):
        require_calibration_release_gate(mutated)
