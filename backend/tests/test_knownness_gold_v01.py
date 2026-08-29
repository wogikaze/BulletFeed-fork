from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.knownness_gold import (
    DATASET_VERSION,
    LABEL_PROTOCOL_VERSION,
    REQUIRED_FAMILIES,
    SAFETY_METRIC,
    SOURCE_FAMILIES,
    delivery_is_known_prediction,
    display_attempt_is_meaningful,
    evaluate_knownness,
    gold_oracle_prediction,
    knownness_release_gate_violations,
    load_knownness_annotations,
    load_knownness_annotations_for_production_scoring,
    load_knownness_gold,
    load_knownness_gold_for_production_scoring,
    load_knownness_manifest,
    replay_derived_knowledge,
    require_knownness_release_gate,
    scan_python_sources,
    show_all_prediction,
)
from app.evaluation.label_contract import (
    PROTOCOL_VERSION,
    AdjudicationRecord,
    AmbiguousFlag,
    LabelFamily,
    apply_adjudication,
    filter_unresolved_ambiguous,
    is_blind_split,
    load_adjudications,
    load_double_labels,
)
from app.evaluation.label_contract_metrics import compute_iaa
from app.services.knowledge_evidence import STATE_UNKNOWN

_V01 = Path(__file__).parent / "gold" / "knownness" / "v01"
_APP = Path(__file__).resolve().parents[1] / "app"
_LEAKAGE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_knownness_gold_leakage.py"
_EXISTING_GOLD = (
    Path(__file__).parent / "gold" / "knowledge_identity_v01.json",
    Path(__file__).parent / "gold" / "label_contract" / "v01" / "annotations.json",
    Path(__file__).parent / "gold" / "personalization" / "v01" / "judgments.json",
)


def _corpus():
    return load_knownness_gold(_V01)


def _predictions(cases, factory):
    return {case.case_id: factory(case) for case in cases}


def test_schema_splits_families_and_label_protocol() -> None:
    corpus = _corpus()
    manifest = load_knownness_manifest(_V01 / "gold_manifest_v01.json")
    schema = json.loads((_V01 / "label_schema.json").read_text(encoding="utf-8"))
    pilot = json.loads((_V01 / "pilot" / "index.json").read_text(encoding="utf-8"))
    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))

    assert corpus.dataset_version == DATASET_VERSION
    assert corpus.label_protocol_version == LABEL_PROTOCOL_VERSION
    assert corpus.label_protocol_version == PROTOCOL_VERSION
    assert manifest.dataset_version == DATASET_VERSION
    assert manifest.protocol_version == PROTOCOL_VERSION
    assert manifest.provenance
    assert "label-protocol-v1" in manifest.provenance
    assert schema["dataset_version"] == DATASET_VERSION
    assert schema["label_protocol_version"] == LABEL_PROTOCOL_VERSION
    assert set(REQUIRED_FAMILIES) <= corpus.families()
    assert len(corpus.cases) >= 40
    assert corpus.source_families() >= {"statuspage", "github_advisory", "osv", "github_release"}
    assert corpus.source_families() <= set(SOURCE_FAMILIES)

    assert {case.case_id for case in corpus.for_split("pilot").cases} == set(pilot["case_ids"])
    assert {case.case_id for case in corpus.for_split("blind").cases} == set(holdout["case_ids"])
    assert set(pilot["case_ids"]).isdisjoint(holdout["case_ids"])
    assert set(pilot["bundle_ids"]).isdisjoint(holdout["bundle_ids"])
    assert set(pilot["user_ids"]).isdisjoint(holdout["user_ids"])
    assert set(pilot["item_ids"]).isdisjoint(holdout["item_ids"])
    assert set(pilot["event_ids"]).isdisjoint(holdout["event_ids"])

    for split in ("pilot", "blind"):
        scoped = corpus.for_split(split)
        assert set(REQUIRED_FAMILIES) <= scoped.families()
        assert any(case.ambiguous for case in scoped.cases)
        assert {case.evidence_type for case in scoped.cases} >= {
            "none",
            "delivered",
            "displayed",
            "read",
            "already_knew",
            "learned_now",
            "baseline",
        }


def test_required_cases_encode_protocol_knownness_rules() -> None:
    corpus = _corpus().for_split("pilot")
    by_family = {case.family: [] for case in corpus.cases}
    for case in corpus.cases:
        if case.ambiguous:
            continue
        by_family[case.family].append(case)

    for case in by_family["never_seen"]:
        assert case.evidence == ()
        assert case.knownness == "new"
        assert case.should_surface is True
        assert case.is_novel_fact is True
    for case in by_family["delivered_not_displayed"]:
        assert {row.kind for row in case.evidence} == {"delivered"}
        assert case.knownness == "new" and case.should_surface
    for case in by_family["briefly_displayed"]:
        assert display_attempt_is_meaningful(case) is False
        assert case.knownness == "new" and case.should_surface
    for case in by_family["meaningfully_displayed"]:
        assert display_attempt_is_meaningful(case) is True
        assert "displayed" in {row.kind for row in case.evidence}
        assert case.knownness == "already_knew" and case.should_surface is False
    for case in by_family["explicitly_read"]:
        assert "read" in {row.kind for row in case.evidence}
        assert case.knownness == "already_knew" and case.should_surface is False
    for case in by_family["already_knew"]:
        assert "already_knew" in {row.kind for row in case.evidence}
        assert case.knownness == "already_knew" and case.should_surface is False
    for case in by_family["learned_now"]:
        assert "learned_now" in {row.kind for row in case.evidence}
        assert case.knownness == "already_knew" and case.should_surface is False
    for case in by_family["cross_source_restatement"]:
        assert case.candidate.relation_to_prior == "equivalent_restatement"
        assert case.candidate.knowledge_id == case.candidate.prior_knowledge_id
        assert case.knownness == "already_knew" and case.should_surface is False
    for case in by_family["added_detail"]:
        assert case.candidate.knowledge_id != case.candidate.prior_knowledge_id
        assert case.knownness == "new" and case.should_surface and case.is_novel_fact
    for case in by_family["correction"]:
        assert case.is_correction
        assert case.knownness == "already_knew" and case.should_surface
    for case in by_family["baseline_before_follow"]:
        assert "baseline" in {row.kind for row in case.evidence}
        assert case.knownness == "already_knew" and case.should_surface is False


def test_oracle_is_perfect_and_passes_safety_gate() -> None:
    corpus = _corpus()
    report = evaluate_knownness(corpus, _predictions(corpus.cases, gold_oracle_prediction))
    metrics = report.exclude_ambiguous
    assert report.safety_metric == SAFETY_METRIC
    assert report.safety_metric == "unknown_but_hidden"
    assert metrics.known.precision == 1.0
    assert metrics.known.recall == 1.0
    assert metrics.novel_fact.precision == 1.0
    assert metrics.novel_fact.recall == 1.0
    assert metrics.known_but_reshown_rate == 0.0
    assert metrics.unknown_but_hidden_rate == 0.0
    assert metrics.correction_recall == 1.0
    assert metrics.by_evidence_type
    assert metrics.by_source_family
    assert {row.segment_key.split("=", 1)[0] for row in metrics.by_evidence_type} == {"evidence_type"}
    assert {row.segment_key.split("=", 1)[0] for row in metrics.by_source_family} == {"source_family"}
    require_knownness_release_gate(report)


def test_delivery_as_known_fails_unknown_but_hidden_safety_gate() -> None:
    corpus = _corpus().for_split("pilot")
    hide = evaluate_knownness(
        corpus,
        _predictions(corpus.cases, delivery_is_known_prediction),
        split="pilot",
    )
    show = evaluate_knownness(
        corpus,
        _predictions(corpus.cases, show_all_prediction),
        split="pilot",
    )
    oracle = evaluate_knownness(
        corpus,
        _predictions(corpus.cases, gold_oracle_prediction),
        split="pilot",
    )

    assert hide.unknown_but_hidden_rate > 0.0
    assert hide.known_but_reshown_rate <= show.known_but_reshown_rate
    assert hide.unknown_but_hidden_rate > show.unknown_but_hidden_rate
    assert hide.correction_recall < 1.0
    assert show.unknown_but_hidden_rate == 0.0
    assert oracle.unknown_but_hidden_rate == 0.0

    hide_violations = knownness_release_gate_violations(hide)
    show_violations = knownness_release_gate_violations(show)
    assert hide_violations
    assert hide_violations[0].startswith("unknown_but_hidden_rate")
    assert any("unknown_but_hidden" in row for row in hide_violations)
    assert any("correction_recall" in row for row in hide_violations)
    assert not any("unknown_but_hidden" in row for row in show_violations)
    with pytest.raises(AssertionError, match="unknown_but_hidden"):
        require_knownness_release_gate(hide)


def test_evaluator_reports_unresolved_ambiguous_separately() -> None:
    corpus = _corpus().for_split("pilot")
    ambiguous = [case for case in corpus.cases if case.ambiguous]
    assert ambiguous
    report = evaluate_knownness(
        corpus,
        _predictions(corpus.cases, gold_oracle_prediction),
        split="pilot",
    )
    assert report.unresolved_ambiguous_count == len(ambiguous)
    assert report.exclude_ambiguous.case_count == len(corpus.cases) - len(ambiguous)
    assert report.include_ambiguous.case_count == len(corpus.cases)


def test_evaluator_replays_recorded_evidence_without_inventing_display() -> None:
    corpus = _corpus().for_split("pilot")
    never = next(case for case in corpus.cases if case.family == "never_seen" and not case.ambiguous)
    brief = next(
        case for case in corpus.cases if case.family == "briefly_displayed" and not case.ambiguous
    )
    replayed = replay_derived_knowledge(never)
    assert replayed.state == STATE_UNKNOWN
    assert replayed.evidence_count == 0
    assert display_attempt_is_meaningful(brief) is False
    brief_replay = replay_derived_knowledge(brief)
    assert brief_replay.evidence_count == len(brief.evidence)
    assert all(row.kind != "displayed" for row in brief.evidence)


def test_double_label_iaa_and_adjudication_do_not_rewrite_source_gold() -> None:
    annotations = load_knownness_annotations(_V01 / "pilot" / "annotations.json")
    pairs = load_double_labels(_V01 / "pilot" / "double_labels.json")
    adjudications = load_adjudications(_V01 / "pilot" / "adjudications.json")
    snapshot = [record.model_dump() for record in annotations]

    assert {pair.pair_id for pair in pairs} >= {
        "kngp-pair-agree-001",
        "kngp-pair-disagree-001",
        "kngp-pair-ambiguous-001",
        "kngp-pair-correction-001",
    }
    report = compute_iaa(pairs, annotations)
    assert report.protocol_version == PROTOCOL_VERSION
    assert report.dataset_version == DATASET_VERSION
    knownness = report.for_family(LabelFamily.KNOWNNESS)
    assert knownness.disagreement_count >= 1
    assert knownness.unresolved_ambiguous_count >= 1
    assert knownness.excluded_unresolved_ambiguous_count >= 1

    filtered = filter_unresolved_ambiguous(annotations, adjudications)
    assert filtered.unresolved_ambiguous
    assert {record.annotation_id for record in filtered.unresolved_ambiguous} >= {
        "kngp-ann-amb-a",
        "kngp-ann-amb-b",
    }

    adjudication = adjudications[0]
    assert adjudication.produced_dataset_version != adjudication.source_dataset_version
    overlay = apply_adjudication(annotations, adjudication)
    assert [record.model_dump() for record in annotations] == snapshot
    assert overlay.dataset_version == "knownness-v0.1.1"
    assert overlay.source_dataset_version == DATASET_VERSION
    assert overlay.overlay_record.judgment_for(LabelFamily.KNOWNNESS).value == "already_knew"
    assert all(record.dataset_version == DATASET_VERSION for record in overlay.unchanged_source_records)

    with pytest.raises(ValidationError, match="new dataset_version"):
        AdjudicationRecord(
            adjudication_id="kngp-adj-bad",
            item_id=adjudication.item_id,
            family=LabelFamily.KNOWNNESS,
            source_annotation_ids=adjudication.source_annotation_ids,
            source_dataset_version=DATASET_VERSION,
            produced_dataset_version=DATASET_VERSION,
            resolved_value="already_knew",
            adjudicator_id="adjudicator-1",
            rationale="must not rewrite in place",
            protocol_version=PROTOCOL_VERSION,
            adjudicated_at="2026-08-29T16:00:00Z",
            provenance="test",
            split="pilot",
        )


def test_blind_split_is_separated_from_production_scoring() -> None:
    blind_path = _V01 / "blind" / "annotations.json"
    assert is_blind_split(path=blind_path)
    assert is_blind_split(path=_V01 / "blind")
    with pytest.raises(ValueError, match="must not be imported by production scoring"):
        load_knownness_annotations_for_production_scoring(blind_path)

    production = load_knownness_annotations_for_production_scoring(_V01 / "pilot" / "annotations.json")
    assert production
    assert all(record.split == "pilot" for record in production)

    pilot_only = load_knownness_gold_for_production_scoring(_V01)
    assert {case.split for case in pilot_only.cases} == {"pilot"}
    assert set(REQUIRED_FAMILIES) <= pilot_only.families()


def test_blind_leakage_guard_for_production_app() -> None:
    holdout = json.loads((_V01 / "blind" / "index.json").read_text(encoding="utf-8"))
    forbidden = {
        "tests/gold/knownness/v01/blind",
        "gold/knownness/v01/blind",
        *holdout["bundle_ids"],
        *holdout["case_ids"],
        *holdout["user_ids"],
        *holdout["item_ids"],
        *holdout["event_ids"],
        *holdout["annotation_ids"],
    }
    assert scan_python_sources(_APP, forbidden) == ()

    try:
        runpy.run_path(str(_LEAKAGE_SCRIPT), run_name="__main__")
    except SystemExit as exc:
        assert exc.code in (0, None)


def test_existing_gold_files_are_not_rewritten() -> None:
    for path in _EXISTING_GOLD:
        assert path.is_file()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload
    identity = json.loads(_EXISTING_GOLD[0].read_text(encoding="utf-8"))
    assert identity["dataset_id"] == "bulletfeed-knowledge-identity-v0.1"
    assert {pair["id"] for pair in identity["pairs"]} >= {"added-detail", "cross-source-latency"}


def test_missing_prediction_raises() -> None:
    corpus = _corpus().for_split("pilot")
    predicted = _predictions(corpus.cases[:2], gold_oracle_prediction)
    with pytest.raises(ValueError, match="missing predictions"):
        evaluate_knownness(corpus, predicted, split="pilot")


def test_annotators_can_leave_knownness_unresolved() -> None:
    annotations = load_knownness_annotations(_V01 / "pilot" / "annotations.json")
    records = {record.annotation_id: record for record in annotations}
    missing = records["kngp-ann-amb-a"].judgment_for(LabelFamily.KNOWNNESS)
    assert missing is not None
    assert missing.ambiguous is AmbiguousFlag.INSUFFICIENT_CONTEXT
    assert missing.value is None
    assert missing.is_unresolved_ambiguous()
