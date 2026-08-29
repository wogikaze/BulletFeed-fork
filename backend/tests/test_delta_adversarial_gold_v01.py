from __future__ import annotations

import json
import runpy
from pathlib import Path

from app.evaluation.delta_adversarial_gold import (
    DATASET_VERSION,
    LABEL_PROTOCOL_VERSION,
    LEXICAL_JACCARD_THRESHOLD,
    REQUIRED_FAMILIES,
    REVISION_CLASSES,
    DeltaAdversarialPrediction,
    evaluate_delta_adversarial,
    gold_oracle_prediction,
    lexical_baseline_prediction,
    load_delta_adversarial_gold,
    load_delta_adversarial_manifest,
    scan_python_sources,
    token_jaccard,
)
from app.services.semantic_delta import ClaimSnapshot, DeltaContext, judge_revision
from app.services.semantic_equivalence import compare_semantic_equivalence

_V01 = Path(__file__).parent / "gold" / "delta_adversarial" / "v01"
_APP = Path(__file__).resolve().parents[1] / "app"
_LEAKAGE_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "check_delta_adversarial_gold_leakage.py"
)


def _corpus():
    return load_delta_adversarial_gold(_V01)


def _predictions(cases, factory):
    return {case.case_id: factory(case) for case in cases}


def test_schema_splits_families_and_provenance() -> None:
    corpus = _corpus()
    manifest = load_delta_adversarial_manifest(_V01 / "gold_manifest_v01.json")
    pilot = json.loads((_V01 / "pilot" / "index.json").read_text(encoding="utf-8"))
    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))

    assert corpus.dataset_version == DATASET_VERSION
    assert corpus.label_protocol_version == LABEL_PROTOCOL_VERSION
    assert manifest["dataset_version"] == DATASET_VERSION
    assert set(REQUIRED_FAMILIES) <= set(manifest["required_families"])
    assert len(corpus.cases) >= 40
    assert len(corpus.cases) >= manifest["minimum_cases"]
    assert len(corpus.hard_negatives()) >= 16
    assert len(corpus.hard_negatives()) >= manifest["minimum_hard_negatives"]
    assert len(corpus.real_cases()) / len(corpus.cases) >= manifest["minimum_real_case_ratio"]
    assert set(REVISION_CLASSES) <= {case.revision_class for case in corpus.cases}
    assert {"equivalent", "not_equivalent", "uncertain"} <= {case.equivalence for case in corpus.cases}

    assert {case.case_id for case in corpus.for_split("pilot").cases} == set(pilot["case_ids"])
    assert {case.case_id for case in corpus.for_split("blind").cases} == set(holdout["case_ids"])
    assert set(pilot["case_ids"]).isdisjoint(holdout["case_ids"])
    assert set(pilot["bundle_ids"]).isdisjoint(holdout["bundle_ids"])
    assert set(pilot["event_ids"]).isdisjoint(holdout["event_ids"])

    for split in ("pilot", "blind"):
        scoped = corpus.for_split(split)
        assert set(REQUIRED_FAMILIES) <= scoped.families()
        assert {case.revision_class for case in scoped.cases}
        assert any(case.kind == "real_public_source" for case in scoped.cases)
        assert any(case.kind == "synthetic_fixed" for case in scoped.cases)
        assert any(case.hard_negative for case in scoped.cases)

    for case in corpus.real_cases():
        assert case.provenance_url.startswith("https://")
        assert case.publisher
    for case in corpus.cases:
        if case.kind == "synthetic_fixed":
            assert not case.provenance_url.startswith("https://")
        assert case.event_label
        assert case.prior_event_id
        assert case.candidate_event_id
        assert case.rationale


def test_gold_labels_are_internally_consistent_and_oracle_is_perfect() -> None:
    corpus = _corpus()
    report = evaluate_delta_adversarial(
        corpus,
        _predictions(corpus.cases, gold_oracle_prediction),
    )
    assert report.pair_count == len(corpus.cases)
    assert report.equivalence.precision == 1.0
    assert report.equivalence.recall == 1.0
    assert report.revision.macro_f1 == 1.0
    assert report.false_merge_count == 0
    assert report.false_split_count == 0
    assert report.uncertain_count == sum(1 for case in corpus.cases if case.equivalence == "uncertain")

    for case in corpus.cases:
        if case.equivalence == "equivalent":
            assert case.revision_class == "NON_NOVEL"
            assert case.same_gold_event
        if case.revision_class == "NEW_FACT":
            assert case.equivalence == "not_equivalent"
        if case.revision_class == "CORRECTION":
            assert case.explicit_correction
        if case.revision_class == "STATE_UPDATE":
            assert case.candidate.valid_at > case.prior.valid_at
            assert case.same_gold_event


def test_lexical_overlap_baseline_fails_target_gate() -> None:
    corpus = _corpus()
    hard = corpus.hard_negatives()
    assert len(hard) >= 16

    high_overlap_splits = [
        case
        for case in hard
        if token_jaccard(case.prior.text, case.candidate.text) >= LEXICAL_JACCARD_THRESHOLD
        and not case.same_gold_event
        and case.equivalence == "not_equivalent"
    ]
    low_overlap_merges = [
        case
        for case in hard
        if token_jaccard(case.prior.text, case.candidate.text) < LEXICAL_JACCARD_THRESHOLD
        and case.same_gold_event
        and case.equivalence == "equivalent"
    ]
    assert len(high_overlap_splits) >= 6
    assert len(low_overlap_merges) >= 4

    lexical = evaluate_delta_adversarial(
        corpus,
        _predictions(corpus.cases, lexical_baseline_prediction),
    )
    oracle = evaluate_delta_adversarial(
        corpus,
        _predictions(corpus.cases, gold_oracle_prediction),
    )
    assert oracle.equivalence.precision == 1.0
    assert oracle.equivalence.recall == 1.0
    assert lexical.equivalence.precision < 0.80
    assert lexical.equivalence.recall < 0.85
    assert lexical.false_merge_count > 0
    assert lexical.false_split_count > 0
    assert lexical.revision.macro_f1 < 0.75


def test_evaluator_reports_equivalence_revision_and_event_identity_separately() -> None:
    corpus = _corpus().for_split("pilot")
    flipped = {}
    for case in corpus.cases:
        flipped[case.case_id] = DeltaAdversarialPrediction(
            case_id=case.case_id,
            equivalence="not_equivalent" if case.equivalence == "equivalent" else "equivalent",
            revision_class="STATE_UPDATE" if case.revision_class != "STATE_UPDATE" else "DETAIL",
            same_event=not case.same_gold_event,
        )
    report = evaluate_delta_adversarial(corpus, flipped, split="pilot")
    assert report.split == "pilot"
    assert report.pair_count == len(corpus.cases)
    assert 0.0 <= report.equivalence.precision <= 1.0
    assert 0.0 <= report.equivalence.recall <= 1.0
    assert 0.0 <= report.revision.macro_f1 <= 1.0
    assert report.false_merge_count + report.false_split_count == len(corpus.cases)


def test_blind_leakage_guard_for_production_app() -> None:
    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))
    forbidden = {
        "tests/gold/delta_adversarial/v01/blind",
        "gold/delta_adversarial/v01/blind",
        *holdout["bundle_ids"],
        *holdout["case_ids"],
        *holdout["event_ids"],
    }
    assert scan_python_sources(_APP, forbidden) == ()

    try:
        runpy.run_path(str(_LEAKAGE_SCRIPT), run_name="__main__")
    except SystemExit as exc:
        assert exc.code in (0, None)


def test_current_algorithm_diagnostic_on_adversarial_set() -> None:
    corpus = _corpus()
    predicted: dict[str, DeltaAdversarialPrediction] = {}
    disagreements = 0
    for case in corpus.cases:
        equivalence = compare_semantic_equivalence(
            case.prior.value,
            case.prior.detail,
            case.candidate.value,
            case.candidate.detail,
        )
        decision = judge_revision(
            ClaimSnapshot(
                value=case.prior.value,
                detail=case.prior.detail,
                valid_at=case.prior.valid_at,
            ),
            ClaimSnapshot(
                value=case.candidate.value,
                detail=case.candidate.detail,
                valid_at=case.candidate.valid_at,
            ),
            context=DeltaContext(
                explicit_correction=case.explicit_correction,
                unresolved_source_conflict=case.unresolved_source_conflict,
            ),
        )
        predicted[case.case_id] = DeltaAdversarialPrediction(
            case_id=case.case_id,
            equivalence=equivalence.label,
            revision_class=decision.revision_type,
            same_event=decision.revision_type != "NEW_FACT",
        )
        if (
            equivalence.label != case.equivalence
            or decision.revision_type != case.revision_class
        ):
            disagreements += 1

    report = evaluate_delta_adversarial(corpus, predicted)
    assert report.pair_count == len(corpus.cases)
    assert 0.0 <= report.equivalence.precision <= 1.0
    assert 0.0 <= report.equivalence.recall <= 1.0
    assert 0.0 <= report.revision.macro_f1 <= 1.0
    assert report.false_merge_count >= 0
    assert report.false_split_count >= 0
    assert disagreements > 0
