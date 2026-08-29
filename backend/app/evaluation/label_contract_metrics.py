from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Sequence

from app.evaluation.label_contract import (
    AmbiguousFlag,
    AnnotationRecord,
    DoubleLabelRecord,
    FamilyIAA,
    FamilyValue,
    IAAReport,
    LabelFamily,
)


def percent_agreement(labels_a: Sequence[Hashable], labels_b: Sequence[Hashable]) -> float:
    if len(labels_a) != len(labels_b):
        raise ValueError("label sequences must have the same length")
    if not labels_a:
        return 1.0
    agreements = sum(left == right for left, right in zip(labels_a, labels_b, strict=True))
    return agreements / len(labels_a)


def cohen_kappa(labels_a: Sequence[Hashable], labels_b: Sequence[Hashable]) -> float | None:
    if len(labels_a) != len(labels_b):
        raise ValueError("label sequences must have the same length")
    if not labels_a:
        return None
    observed = percent_agreement(labels_a, labels_b)
    categories = sorted(set(labels_a) | set(labels_b), key=str)
    n = len(labels_a)
    count_a = Counter(labels_a)
    count_b = Counter(labels_b)
    expected = sum((count_a[category] / n) * (count_b[category] / n) for category in categories)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def compute_iaa(
    pairs: Sequence[DoubleLabelRecord],
    annotations: Sequence[AnnotationRecord],
    *,
    exclude_unresolved_ambiguous: bool = True,
) -> IAAReport:
    by_id = {record.annotation_id: record for record in annotations}
    if not pairs:
        raise ValueError("IAA requires at least one double-label pair")
    protocol_versions = {pair.protocol_version for pair in pairs}
    dataset_versions = {pair.dataset_version for pair in pairs}
    if len(protocol_versions) != 1 or len(dataset_versions) != 1:
        raise ValueError("double-label pairs must share protocol_version and dataset_version")

    families = _ordered_families(pairs)
    family_rows: list[FamilyIAA] = []
    excluded_total = 0
    for family in families:
        comparable_a: list[FamilyValue] = []
        comparable_b: list[FamilyValue] = []
        unresolved = 0
        excluded = 0
        for pair in pairs:
            if family not in pair.families:
                continue
            left = _require_annotation(by_id, pair.annotation_a_id, pair.pair_id)
            right = _require_annotation(by_id, pair.annotation_b_id, pair.pair_id)
            left_judgment = left.judgment_for(family)
            right_judgment = right.judgment_for(family)
            if left_judgment is None or right_judgment is None:
                raise ValueError(f"pair {pair.pair_id} is missing {family} on one annotation")
            if left_judgment.is_unresolved_ambiguous() or right_judgment.is_unresolved_ambiguous():
                unresolved += 1
                if exclude_unresolved_ambiguous:
                    excluded += 1
                    continue
            if left_judgment.value is None or right_judgment.value is None:
                unresolved += 1
                if exclude_unresolved_ambiguous:
                    excluded += 1
                    continue
            comparable_a.append(left_judgment.value)
            comparable_b.append(right_judgment.value)
        agreements = sum(left == right for left, right in zip(comparable_a, comparable_b, strict=True))
        pair_count = len(comparable_a)
        family_rows.append(
            FamilyIAA(
                family=family,
                pair_count=pair_count,
                agreement_count=agreements,
                disagreement_count=pair_count - agreements,
                percent_agreement=percent_agreement(comparable_a, comparable_b) if pair_count else 1.0,
                cohen_kappa=cohen_kappa(comparable_a, comparable_b),
                unresolved_ambiguous_count=unresolved,
                excluded_unresolved_ambiguous_count=excluded,
            )
        )
        excluded_total += excluded

    return IAAReport(
        protocol_version=next(iter(protocol_versions)),
        dataset_version=next(iter(dataset_versions)),
        pair_count=len(pairs),
        by_family=tuple(family_rows),
        excluded_unresolved_ambiguous_count=excluded_total,
    )


def _ordered_families(pairs: Sequence[DoubleLabelRecord]) -> tuple[LabelFamily, ...]:
    seen: list[LabelFamily] = []
    for pair in pairs:
        for family in pair.families:
            if family not in seen:
                seen.append(family)
    return tuple(seen)


def _require_annotation(
    by_id: dict[str, AnnotationRecord],
    annotation_id: str,
    pair_id: str,
) -> AnnotationRecord:
    try:
        return by_id[annotation_id]
    except KeyError as exc:
        raise ValueError(f"pair {pair_id} references unknown annotation {annotation_id}") from exc


def family_disagreement_rows(
    pairs: Sequence[DoubleLabelRecord],
    annotations: Sequence[AnnotationRecord],
    family: LabelFamily,
) -> tuple[dict[str, object], ...]:
    by_id = {record.annotation_id: record for record in annotations}
    rows: list[dict[str, object]] = []
    for pair in pairs:
        if family not in pair.families:
            continue
        left = _require_annotation(by_id, pair.annotation_a_id, pair.pair_id)
        right = _require_annotation(by_id, pair.annotation_b_id, pair.pair_id)
        left_judgment = left.judgment_for(family)
        right_judgment = right.judgment_for(family)
        if left_judgment is None or right_judgment is None:
            continue
        left_open = left_judgment.ambiguous is not AmbiguousFlag.NONE
        right_open = right_judgment.ambiguous is not AmbiguousFlag.NONE
        if left_open or right_open:
            continue
        if left_judgment.value == right_judgment.value:
            continue
        rows.append(
            {
                "pair_id": pair.pair_id,
                "item_id": pair.item_id,
                "family": family.value,
                "annotator_a": left.annotator_id,
                "annotator_b": right.annotator_id,
                "value_a": left_judgment.value,
                "value_b": right_judgment.value,
            }
        )
    return tuple(rows)
