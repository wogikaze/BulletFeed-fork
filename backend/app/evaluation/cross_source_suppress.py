"""Gold evaluation for cross-source repetition control (Known-06)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.cross_source_suppress import (
    POLICY_VERSION,
    SourceCandidate,
    project_candidates,
)

DATASET_VERSION = "cross-source-suppress-v0.1"
POLICY_ID = POLICY_VERSION

REQUIRED_FAMILIES: tuple[str, ...] = (
    "duplicate_press_release",
    "syndication",
    "independent_confirmation",
    "added_detail",
    "contradiction",
)


@dataclass(frozen=True)
class CrossSourceCase:
    case_id: str
    family: str
    candidates: tuple[SourceCandidate, ...]
    expected_displayed_ids: tuple[str, ...]
    expected_additional_ids: tuple[str, ...]
    expected_hidden_ids: tuple[str, ...]
    expected_independent_evidence_count: int
    should_surface: bool
    rationale: str


@dataclass(frozen=True)
class CrossSourceReport:
    dataset_version: str
    policy_version: str
    case_count: int
    unknown_but_hidden_count: int
    duplicate_card_count: int
    false_suppression_rate: float
    duplicate_card_rate: float


def load_cross_source_gold(path: Path) -> tuple[CrossSourceCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("dataset_id") != "bulletfeed-cross-source-suppress-v0.1":
        raise ValueError("unexpected cross-source-suppress dataset_id")
    if payload.get("version") != POLICY_VERSION:
        raise ValueError("unexpected cross-source-suppress version")
    cases = tuple(_case_from_payload(item) for item in payload["cases"])
    _validate_corpus(cases)
    return cases


def project_case(case: CrossSourceCase):
    return project_candidates(case.candidates)


def evaluate_cross_source(
    cases: Sequence[CrossSourceCase],
) -> CrossSourceReport:
    unknown_hidden = 0
    unknown = 0
    duplicate_cards = 0
    collapse_cases = 0
    for case in cases:
        batch = project_case(case)
        if case.should_surface:
            unknown += 1
            if not batch.displayed_ids:
                unknown_hidden += 1
        if case.family in {
            "duplicate_press_release",
            "syndication",
            "independent_confirmation",
        }:
            collapse_cases += 1
            extra = [item for item in batch.displayed_ids if item not in case.expected_displayed_ids]
            if extra:
                duplicate_cards += 1
    return CrossSourceReport(
        dataset_version=DATASET_VERSION,
        policy_version=POLICY_VERSION,
        case_count=len(cases),
        unknown_but_hidden_count=unknown_hidden,
        duplicate_card_count=duplicate_cards,
        false_suppression_rate=_ratio(unknown_hidden, unknown),
        duplicate_card_rate=_ratio(duplicate_cards, collapse_cases, empty=0.0),
    )


def _case_from_payload(item: Mapping[str, Any]) -> CrossSourceCase:
    expect = item["expect"]
    return CrossSourceCase(
        case_id=str(item["id"]),
        family=str(item["family"]),
        candidates=tuple(_candidate_from_payload(row) for row in item["candidates"]),
        expected_displayed_ids=tuple(expect["displayed_ids"]),
        expected_additional_ids=tuple(expect["additional_source_ids"]),
        expected_hidden_ids=tuple(expect["hidden_ids"]),
        expected_independent_evidence_count=int(expect["independent_evidence_count"]),
        should_surface=bool(expect["should_surface"]),
        rationale=str(item["rationale"]),
    )


def _candidate_from_payload(item: Mapping[str, Any]) -> SourceCandidate:
    return SourceCandidate(
        candidate_id=str(item["id"]),
        source_id=str(item["source_id"]),
        publisher=str(item["publisher"]),
        kind=str(item["kind"]),
        title=str(item["title"]),
        url=str(item["url"]),
        published_at=str(item["published_at"]),
        retrieved_at=str(item["retrieved_at"]),
        evidence=str(item["evidence"]),
        value=str(item.get("value") or ""),
        detail=str(item.get("detail") or ""),
        slot=str(item.get("slot") or ""),
        revision_class=item.get("revision_class"),
        dependence_key=item.get("dependence_key"),
        knowledge_state=str(item.get("knowledge_state") or "unknown"),
        knowledge_confidence=str(item.get("knowledge_confidence") or "none"),
        importance_level=item.get("importance_level"),
        stale_exposure=bool(item.get("stale_exposure", False)),
        identity_label=item.get("identity_label"),
        identity_confidence=item.get("identity_confidence"),
        equivalence_label=item.get("equivalence_label"),
    )


def _validate_corpus(cases: Sequence[CrossSourceCase]) -> None:
    if not cases:
        raise ValueError("cross-source-suppress corpus has no cases")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate cross-source-suppress case ids")
    missing = set(REQUIRED_FAMILIES) - {case.family for case in cases}
    if missing:
        raise ValueError(f"corpus missing required families: {sorted(missing)}")


def _ratio(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    if denominator == 0:
        return empty
    return numerator / denominator


__all__ = (
    "DATASET_VERSION",
    "POLICY_ID",
    "REQUIRED_FAMILIES",
    "CrossSourceCase",
    "CrossSourceReport",
    "evaluate_cross_source",
    "load_cross_source_gold",
    "project_case",
)
