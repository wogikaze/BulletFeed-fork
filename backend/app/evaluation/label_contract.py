from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL_VERSION = "label-protocol-v1"
PROTOCOL_DOC_RELATIVE_PATH = "docs/evaluation/gold-labeling-protocol.md"
BLIND_SPLIT = "blind"
PILOT_SPLIT = "pilot"
BLIND_PATH_SEGMENT = "blind"

RelevanceValue = Literal[0, 1, 2, 3]
UserImportanceValue = Literal[0, 1, 2, 3]
SemanticEquivalenceValue = Literal["equivalent", "not_equivalent", "uncertain"]
NoveltyRevisionValue = Literal[
    "NEW_FACT",
    "DETAIL",
    "STATE_UPDATE",
    "CORRECTION",
    "UNRESOLVED_CONTRADICTION",
    "NON_NOVEL",
]
KnownnessValue = Literal["already_knew", "new"]
ShouldSurfaceValue = Literal[True, False]
DatasetSplit = Literal["pilot", "blind"]
FamilyValue = int | str | bool

RELEVANCE_VALUES: tuple[int, ...] = (0, 1, 2, 3)
USER_IMPORTANCE_VALUES: tuple[int, ...] = (0, 1, 2, 3)
SEMANTIC_EQUIVALENCE_VALUES: tuple[str, ...] = ("equivalent", "not_equivalent", "uncertain")
NOVELTY_REVISION_VALUES: tuple[str, ...] = (
    "NEW_FACT",
    "DETAIL",
    "STATE_UPDATE",
    "CORRECTION",
    "UNRESOLVED_CONTRADICTION",
    "NON_NOVEL",
)
KNOWNNESS_VALUES: tuple[str, ...] = ("already_knew", "new")
SHOULD_SURFACE_VALUES: tuple[bool, ...] = (True, False)


class LabelFamily(StrEnum):
    RELEVANCE = "relevance"
    USER_IMPORTANCE = "user_importance"
    SEMANTIC_EQUIVALENCE = "semantic_equivalence"
    NOVELTY_REVISION = "novelty_revision"
    KNOWNNESS = "knownness"
    SHOULD_SURFACE = "should_surface"


class AmbiguousFlag(StrEnum):
    NONE = "none"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_CONTEXT = "insufficient_context"


_FAMILY_ALLOWED_VALUES: dict[LabelFamily, frozenset[FamilyValue]] = {
    LabelFamily.RELEVANCE: frozenset(RELEVANCE_VALUES),
    LabelFamily.USER_IMPORTANCE: frozenset(USER_IMPORTANCE_VALUES),
    LabelFamily.SEMANTIC_EQUIVALENCE: frozenset(SEMANTIC_EQUIVALENCE_VALUES),
    LabelFamily.NOVELTY_REVISION: frozenset(NOVELTY_REVISION_VALUES),
    LabelFamily.KNOWNNESS: frozenset(KNOWNNESS_VALUES),
    LabelFamily.SHOULD_SURFACE: frozenset(SHOULD_SURFACE_VALUES),
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FamilyJudgment(_FrozenModel):
    family: LabelFamily
    value: FamilyValue | None = None
    ambiguous: AmbiguousFlag = AmbiguousFlag.NONE
    rationale: str = ""

    @model_validator(mode="after")
    def validate_family_value(self) -> Self:
        if self.ambiguous is AmbiguousFlag.NONE and self.value is None:
            raise ValueError(f"{self.family} requires a value unless marked ambiguous or insufficient_context")
        if self.value is None:
            return self
        allowed = _FAMILY_ALLOWED_VALUES[self.family]
        if self.value not in allowed:
            raise ValueError(f"invalid {self.family} value {self.value!r}; allowed={sorted(allowed, key=str)}")
        return self

    def is_forced_label(self) -> bool:
        return self.ambiguous is AmbiguousFlag.NONE

    def is_unresolved_ambiguous(self) -> bool:
        return self.ambiguous is not AmbiguousFlag.NONE


class AnnotationRecord(_FrozenModel):
    annotation_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    annotator_id: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    split: DatasetSplit
    judgments: tuple[FamilyJudgment, ...] = Field(min_length=1)
    provenance: str = Field(min_length=1)
    labeled_at: str = Field(min_length=1)
    notes: str = ""

    @model_validator(mode="after")
    def validate_unique_families(self) -> Self:
        families = [judgment.family for judgment in self.judgments]
        if len(families) != len(set(families)):
            raise ValueError(f"annotation {self.annotation_id} repeats a label family")
        return self

    def judgment_for(self, family: LabelFamily) -> FamilyJudgment | None:
        for judgment in self.judgments:
            if judgment.family == family:
                return judgment
        return None


class DoubleLabelRecord(_FrozenModel):
    pair_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    annotation_a_id: str = Field(min_length=1)
    annotation_b_id: str = Field(min_length=1)
    annotator_a_id: str = Field(min_length=1)
    annotator_b_id: str = Field(min_length=1)
    families: tuple[LabelFamily, ...] = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    split: DatasetSplit

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        if self.annotation_a_id == self.annotation_b_id:
            raise ValueError(f"double-label pair {self.pair_id} references the same annotation twice")
        if self.annotator_a_id == self.annotator_b_id:
            raise ValueError(f"double-label pair {self.pair_id} must use two distinct annotators")
        if len(self.families) != len(set(self.families)):
            raise ValueError(f"double-label pair {self.pair_id} repeats a label family")
        return self


class AdjudicationRecord(_FrozenModel):
    adjudication_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    family: LabelFamily
    source_annotation_ids: tuple[str, ...] = Field(min_length=1)
    source_dataset_version: str = Field(min_length=1)
    produced_dataset_version: str = Field(min_length=1)
    resolved_value: FamilyValue | None = None
    resolved_ambiguous: AmbiguousFlag = AmbiguousFlag.NONE
    adjudicator_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    adjudicated_at: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    split: DatasetSplit

    @model_validator(mode="after")
    def validate_version_and_value(self) -> Self:
        if self.produced_dataset_version == self.source_dataset_version:
            raise ValueError("adjudication must produce a new dataset_version rather than rewrite Gold in place")
        if self.resolved_ambiguous is AmbiguousFlag.NONE and self.resolved_value is None:
            raise ValueError("resolved adjudication requires a value unless it remains ambiguous")
        if self.resolved_value is None:
            return self
        allowed = _FAMILY_ALLOWED_VALUES[self.family]
        if self.resolved_value not in allowed:
            raise ValueError(f"invalid adjudicated {self.family} value {self.resolved_value!r}")
        return self


class DatasetManifest(_FrozenModel):
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    split: DatasetSplit | Literal["mixed"]
    provenance: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    description: str = ""
    parent_dataset_version: str | None = None
    annotation_ids: tuple[str, ...] = ()
    double_label_ids: tuple[str, ...] = ()
    adjudication_ids: tuple[str, ...] = ()
    entry_ids: tuple[str, ...] = ()


class FamilyIAA(_FrozenModel):
    family: LabelFamily
    pair_count: int
    agreement_count: int
    disagreement_count: int
    percent_agreement: float
    cohen_kappa: float | None
    unresolved_ambiguous_count: int
    excluded_unresolved_ambiguous_count: int


class IAAReport(_FrozenModel):
    protocol_version: str
    dataset_version: str
    pair_count: int
    by_family: tuple[FamilyIAA, ...]
    excluded_unresolved_ambiguous_count: int

    def for_family(self, family: LabelFamily) -> FamilyIAA:
        for row in self.by_family:
            if row.family == family:
                return row
        raise KeyError(family)


class AmbiguousFilterResult(_FrozenModel):
    scorable: tuple[AnnotationRecord, ...]
    unresolved_ambiguous: tuple[AnnotationRecord, ...]


class AdjudicationOverlay(_FrozenModel):
    adjudication_id: str
    source_dataset_version: str
    dataset_version: str
    overlay_record: AnnotationRecord
    unchanged_source_records: tuple[AnnotationRecord, ...]


def is_blind_split(
    split: str | None = None,
    path: str | Path | None = None,
) -> bool:
    if split == BLIND_SPLIT:
        return True
    if path is not None:
        return BLIND_PATH_SEGMENT in Path(path).parts
    return False


def assert_not_blind_for_production_scoring(
    records: Iterable[AnnotationRecord] = (),
    *,
    path: str | Path | None = None,
    split: str | None = None,
) -> None:
    if is_blind_split(split=split, path=path):
        raise ValueError("split=blind records must not be imported by production scoring code")
    for record in records:
        if is_blind_split(record.split):
            raise ValueError(
                f"split=blind record {record.annotation_id} must not be imported by production scoring code"
            )


def filter_unresolved_ambiguous(
    records: Sequence[AnnotationRecord],
    adjudications: Sequence[AdjudicationRecord] = (),
) -> AmbiguousFilterResult:
    resolved_keys = {
        (row.item_id, row.family)
        for row in adjudications
        if row.resolved_ambiguous is AmbiguousFlag.NONE
    }
    scorable: list[AnnotationRecord] = []
    unresolved: list[AnnotationRecord] = []
    for record in records:
        if any(
            judgment.is_unresolved_ambiguous() and (record.item_id, judgment.family) not in resolved_keys
            for judgment in record.judgments
        ):
            unresolved.append(record)
        else:
            scorable.append(record)
    return AmbiguousFilterResult(tuple(scorable), tuple(unresolved))


def apply_adjudication(
    records: Sequence[AnnotationRecord],
    adjudication: AdjudicationRecord,
) -> AdjudicationOverlay:
    source_ids = set(adjudication.source_annotation_ids)
    sources = tuple(record.model_copy(deep=True) for record in records if record.annotation_id in source_ids)
    if len(sources) != len(source_ids):
        missing = source_ids - {record.annotation_id for record in sources}
        raise ValueError(f"adjudication {adjudication.adjudication_id} missing source annotations: {sorted(missing)}")
    mismatched = [record.annotation_id for record in sources if record.item_id != adjudication.item_id]
    if mismatched:
        raise ValueError(f"adjudication {adjudication.adjudication_id} item_id does not match {mismatched}")

    overlay = AnnotationRecord(
        annotation_id=f"overlay:{adjudication.adjudication_id}",
        item_id=adjudication.item_id,
        annotator_id=adjudication.adjudicator_id,
        protocol_version=adjudication.protocol_version,
        dataset_version=adjudication.produced_dataset_version,
        split=adjudication.split,
        judgments=(
            FamilyJudgment(
                family=adjudication.family,
                value=adjudication.resolved_value,
                ambiguous=adjudication.resolved_ambiguous,
                rationale=adjudication.rationale,
            ),
        ),
        provenance=f"adjudication_id={adjudication.adjudication_id}; {adjudication.provenance}",
        labeled_at=adjudication.adjudicated_at,
        notes="adjudication overlay; source Gold records are unchanged",
    )
    return AdjudicationOverlay(
        adjudication_id=adjudication.adjudication_id,
        source_dataset_version=adjudication.source_dataset_version,
        dataset_version=adjudication.produced_dataset_version,
        overlay_record=overlay,
        unchanged_source_records=sources,
    )


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_json_array(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return payload


def load_dataset_manifest(path: Path) -> DatasetManifest:
    return DatasetManifest.model_validate(load_json_object(path))


def load_annotations(path: Path) -> tuple[AnnotationRecord, ...]:
    return tuple(AnnotationRecord.model_validate(row) for row in load_json_array(path))


def load_double_labels(path: Path) -> tuple[DoubleLabelRecord, ...]:
    return tuple(DoubleLabelRecord.model_validate(row) for row in load_json_array(path))


def load_adjudications(path: Path) -> tuple[AdjudicationRecord, ...]:
    return tuple(AdjudicationRecord.model_validate(row) for row in load_json_array(path))


def load_annotations_for_production_scoring(path: Path) -> tuple[AnnotationRecord, ...]:
    records = load_annotations(path)
    assert_not_blind_for_production_scoring(records, path=path)
    return records
