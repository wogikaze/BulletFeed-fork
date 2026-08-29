from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.label_contract import (
    PROTOCOL_DOC_RELATIVE_PATH,
    PROTOCOL_VERSION,
    AdjudicationRecord,
    AmbiguousFlag,
    AnnotationRecord,
    DatasetManifest,
    FamilyJudgment,
    LabelFamily,
    apply_adjudication,
    assert_not_blind_for_production_scoring,
    filter_unresolved_ambiguous,
    is_blind_split,
    load_adjudications,
    load_annotations,
    load_annotations_for_production_scoring,
    load_dataset_manifest,
    load_double_labels,
)
from app.evaluation.label_contract_metrics import (
    cohen_kappa,
    compute_iaa,
    family_disagreement_rows,
    percent_agreement,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_V01 = Path(__file__).parent / "gold" / "label_contract" / "v01"
_GUIDE = _REPO_ROOT / PROTOCOL_DOC_RELATIVE_PATH
_REQUIRED_FAMILY_HEADINGS = (
    "relevance",
    "user-importance",
    "semantic equivalence",
    "novelty / revision",
    "knownness",
    "should_surface",
)


def _annotations() -> tuple[AnnotationRecord, ...]:
    return load_annotations(_V01 / "annotations.json")


def _pairs():
    return load_double_labels(_V01 / "double_labels.json")


def _adjudications() -> tuple[AdjudicationRecord, ...]:
    return load_adjudications(_V01 / "adjudications.json")


def test_guide_defines_every_label_family_with_positive_and_negative_examples() -> None:
    assert _GUIDE.is_file()
    text = _GUIDE.read_text(encoding="utf-8")
    assert PROTOCOL_VERSION in text
    assert "正例" in text
    assert "負例" in text
    examples = text.split("## 8.", maxsplit=1)[1]
    for heading in _REQUIRED_FAMILY_HEADINGS:
        assert heading in examples
        start = examples.lower().index(heading)
        window = examples[start : start + 2800]
        assert "正例" in window, heading
        assert "負例" in window, heading
    assert "ambiguous" in text
    assert "insufficient_context" in text
    assert "パイロット" in text
    assert "ブラインド" in text
    assert "裁定" in text
    assert "dataset_version" in text
    assert "already_knew" in text
    assert "equivalent" in text
    assert "not_equivalent" in text
    assert "uncertain" in text


def test_annotators_can_mark_ambiguous_or_insufficient_context_instead_of_forcing_a_label() -> None:
    records = {record.annotation_id: record for record in _annotations()}
    missing_context = records["ann-ambiguous-a"].judgment_for(LabelFamily.RELEVANCE)
    tentative = records["ann-ambiguous-b"].judgment_for(LabelFamily.RELEVANCE)
    assert missing_context is not None
    assert missing_context.ambiguous is AmbiguousFlag.INSUFFICIENT_CONTEXT
    assert missing_context.value is None
    assert missing_context.is_unresolved_ambiguous()
    assert tentative is not None
    assert tentative.ambiguous is AmbiguousFlag.AMBIGUOUS
    assert tentative.value == 1

    forced = FamilyJudgment(family=LabelFamily.RELEVANCE, value=2, ambiguous=AmbiguousFlag.NONE)
    assert forced.is_forced_label()
    with pytest.raises(ValidationError, match="requires a value"):
        FamilyJudgment(family=LabelFamily.RELEVANCE, value=None, ambiguous=AmbiguousFlag.NONE)


def test_double_labeled_fixture_validates_the_schema() -> None:
    annotations = _annotations()
    pairs = _pairs()
    by_id = {record.annotation_id: record for record in annotations}

    assert len(pairs) >= 3
    pair_ids = {pair.pair_id for pair in pairs}
    assert {"pair-agree-001", "pair-disagree-001", "pair-ambiguous-001"} <= pair_ids
    seen_families: set[LabelFamily] = set()
    for pair in pairs:
        left = by_id[pair.annotation_a_id]
        right = by_id[pair.annotation_b_id]
        assert left.item_id == right.item_id == pair.item_id
        assert left.annotator_id != right.annotator_id
        assert left.split == "pilot"
        assert right.split == "pilot"
        for family in pair.families:
            assert left.judgment_for(family) is not None
            assert right.judgment_for(family) is not None
            seen_families.add(family)
    assert seen_families == set(LabelFamily)


def test_iaa_and_disagreement_are_reported_by_label_family() -> None:
    report = compute_iaa(_pairs(), _annotations())
    assert report.protocol_version == PROTOCOL_VERSION
    assert report.dataset_version == "label-contract-v0.1"
    assert {row.family for row in report.by_family} == set(LabelFamily)

    relevance = report.for_family(LabelFamily.RELEVANCE)
    assert relevance.pair_count == 2
    assert relevance.agreement_count == 1
    assert relevance.disagreement_count == 1
    assert relevance.percent_agreement == 0.5
    assert relevance.unresolved_ambiguous_count == 1
    assert relevance.excluded_unresolved_ambiguous_count == 1
    assert relevance.cohen_kappa == pytest.approx(1 / 3)

    importance = report.for_family(LabelFamily.USER_IMPORTANCE)
    assert importance.pair_count == 2
    assert importance.disagreement_count == 0
    assert importance.percent_agreement == 1.0
    assert importance.cohen_kappa == 1.0

    disagreements = family_disagreement_rows(_pairs(), _annotations(), LabelFamily.RELEVANCE)
    assert len(disagreements) == 1
    assert disagreements[0]["pair_id"] == "pair-disagree-001"
    assert disagreements[0]["value_a"] == 2
    assert disagreements[0]["value_b"] == 1


def test_adjudication_retains_history_and_does_not_mutate_prior_gold() -> None:
    originals = _annotations()
    snapshot = [record.model_dump() for record in originals]
    adjudication = _adjudications()[0]
    assert adjudication.adjudication_id == "adj-equivalence-001"
    assert adjudication.produced_dataset_version != adjudication.source_dataset_version

    overlay = apply_adjudication(originals, adjudication)

    assert [record.model_dump() for record in originals] == snapshot
    assert [record.model_dump() for record in overlay.unchanged_source_records] == [
        record.model_dump()
        for record in originals
        if record.annotation_id in adjudication.source_annotation_ids
    ]
    assert overlay.dataset_version == "label-contract-v0.1.1"
    assert overlay.source_dataset_version == "label-contract-v0.1"
    assert overlay.overlay_record.dataset_version == overlay.dataset_version
    assert overlay.overlay_record.annotation_id == "overlay:adj-equivalence-001"
    assert overlay.overlay_record.judgment_for(LabelFamily.SEMANTIC_EQUIVALENCE).value == "equivalent"
    assert all(record.dataset_version == "label-contract-v0.1" for record in originals)
    assert overlay.overlay_record.annotation_id not in {record.annotation_id for record in originals}

    with pytest.raises(ValidationError, match="new dataset_version"):
        AdjudicationRecord(
            adjudication_id="adj-bad",
            item_id="item-adjudicate-001",
            family=LabelFamily.SEMANTIC_EQUIVALENCE,
            source_annotation_ids=("ann-adjudicate-a",),
            source_dataset_version="label-contract-v0.1",
            produced_dataset_version="label-contract-v0.1",
            resolved_value="equivalent",
            adjudicator_id="adjudicator-1",
            rationale="must not rewrite in place",
            protocol_version=PROTOCOL_VERSION,
            adjudicated_at="2026-08-29T12:00:00Z",
            provenance="test",
            split="pilot",
        )


def test_blind_split_is_separated_from_production_scoring() -> None:
    blind_path = _V01 / "blind" / "annotations.json"
    blind_records = load_annotations(blind_path)
    assert all(record.split == "blind" for record in blind_records)
    assert is_blind_split(split="blind")
    assert is_blind_split(path=blind_path)
    assert is_blind_split(path=_V01 / "blind")
    assert not is_blind_split(split="pilot", path=_V01 / "annotations.json")

    with pytest.raises(ValueError, match="must not be imported by production scoring"):
        load_annotations_for_production_scoring(blind_path)
    with pytest.raises(ValueError, match="must not be imported by production scoring"):
        assert_not_blind_for_production_scoring(blind_records)
    with pytest.raises(ValueError, match="must not be imported by production scoring"):
        assert_not_blind_for_production_scoring(path=_V01 / "blind")

    production = load_annotations_for_production_scoring(_V01 / "annotations.json")
    assert production
    assert all(record.split == "pilot" for record in production)


def test_manifest_records_protocol_version_and_provenance() -> None:
    manifest = load_dataset_manifest(_V01 / "gold_manifest_v01.json")
    raw = json.loads((_V01 / "gold_manifest_v01.json").read_text(encoding="utf-8"))
    assert isinstance(manifest, DatasetManifest)
    assert manifest.protocol_version == PROTOCOL_VERSION
    assert manifest.dataset_version == "label-contract-v0.1"
    assert manifest.provenance
    assert "label-protocol-v1" in manifest.provenance
    assert raw["protocol_version"] == PROTOCOL_VERSION
    assert raw["provenance"]
    assert raw["split"] in {"pilot", "blind", "mixed"}
    assert "adj-equivalence-001" in manifest.adjudication_ids
    assert "pair-disagree-001" in manifest.double_label_ids


def test_filter_unresolved_ambiguous_excludes_or_reports_separately() -> None:
    result = filter_unresolved_ambiguous(_annotations())
    unresolved_ids = {record.annotation_id for record in result.unresolved_ambiguous}
    scorable_ids = {record.annotation_id for record in result.scorable}
    assert unresolved_ids == {"ann-ambiguous-a", "ann-ambiguous-b"}
    assert "ann-agree-a" in scorable_ids
    assert "ann-ambiguous-a" not in scorable_ids

    resolved = filter_unresolved_ambiguous(_annotations(), _adjudications())
    assert {record.annotation_id for record in resolved.unresolved_ambiguous} == unresolved_ids


def test_cohen_kappa_and_percent_agreement_match_hand_calculation() -> None:
    left = (0, 1, 0, 1)
    right = (0, 1, 1, 1)
    assert percent_agreement(left, right) == 0.75
    assert cohen_kappa(left, right) == pytest.approx(0.5)
    assert cohen_kappa((), ()) is None
    assert percent_agreement((), ()) == 1.0
    assert cohen_kappa((1, 1), (1, 1)) == 1.0
