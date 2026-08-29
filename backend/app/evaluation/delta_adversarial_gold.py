from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.semantic_quality import (
    BinaryMetricReport,
    RevisionMetricReport,
    binary_metrics,
    revision_metrics,
)

DATASET_VERSION = "delta-adversarial-v0.1"
LABEL_PROTOCOL_VERSION = "delta-adversarial-label-v1"
LEXICAL_JACCARD_THRESHOLD = 0.50
REQUIRED_FAMILIES = (
    "same_fact_different_wording",
    "same_words_different_fact",
    "numeric_version_date_unit",
    "negation_comparator",
    "partial_detail_vs_restatement",
    "correction_vs_state_update",
    "delayed_out_of_order",
    "cross_source_restatement",
    "japanese_mixed_technical",
    "entity_alias_product_rename",
)
EQUIVALENCE_LABELS = ("equivalent", "not_equivalent", "uncertain")
REVISION_CLASSES = (
    "NEW_FACT",
    "NON_NOVEL",
    "DETAIL",
    "STATE_UPDATE",
    "CORRECTION",
    "UNRESOLVED_CONTRADICTION",
)
SplitName = Literal["pilot", "blind"]
KindName = Literal["real_public_source", "synthetic_fixed"]
EquivalenceLabel = Literal["equivalent", "not_equivalent", "uncertain"]
RevisionClass = Literal[
    "NEW_FACT",
    "NON_NOVEL",
    "DETAIL",
    "STATE_UPDATE",
    "CORRECTION",
    "UNRESOLVED_CONTRADICTION",
]
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", re.IGNORECASE)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimRecord(_StrictModel):
    value: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    valid_at: str = Field(min_length=1)


class CaseRecord(_StrictModel):
    case_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    split: SplitName
    family: Literal[
        "same_fact_different_wording",
        "same_words_different_fact",
        "numeric_version_date_unit",
        "negation_comparator",
        "partial_detail_vs_restatement",
        "correction_vs_state_update",
        "delayed_out_of_order",
        "cross_source_restatement",
        "japanese_mixed_technical",
        "entity_alias_product_rename",
    ]
    kind: KindName
    hard_negative: bool
    publisher: str = Field(min_length=1)
    provenance_url: str
    prior: ClaimRecord
    candidate: ClaimRecord
    equivalence: EquivalenceLabel
    revision_class: RevisionClass
    event_label: str = Field(min_length=1)
    prior_event_id: str = Field(min_length=1)
    candidate_event_id: str = Field(min_length=1)
    explicit_correction: bool = False
    unresolved_source_conflict: bool = False
    rationale: str = Field(min_length=1)


@dataclass(frozen=True)
class DeltaAdversarialClaim:
    value: str
    detail: str
    valid_at: str

    @property
    def text(self) -> str:
        return f"{self.value} {self.detail}"


@dataclass(frozen=True)
class DeltaAdversarialCase:
    case_id: str
    bundle_id: str
    split: SplitName
    family: str
    kind: KindName
    hard_negative: bool
    publisher: str
    provenance_url: str
    prior: DeltaAdversarialClaim
    candidate: DeltaAdversarialClaim
    equivalence: EquivalenceLabel
    revision_class: RevisionClass
    event_label: str
    prior_event_id: str
    candidate_event_id: str
    explicit_correction: bool
    unresolved_source_conflict: bool
    rationale: str

    @property
    def same_gold_event(self) -> bool:
        return self.prior_event_id == self.candidate_event_id


@dataclass(frozen=True)
class DeltaAdversarialCorpus:
    dataset_version: str
    label_protocol_version: str
    cases: tuple[DeltaAdversarialCase, ...]

    def for_split(self, split: str) -> DeltaAdversarialCorpus:
        return DeltaAdversarialCorpus(
            dataset_version=self.dataset_version,
            label_protocol_version=self.label_protocol_version,
            cases=tuple(case for case in self.cases if case.split == split),
        )

    def case_by_id(self) -> dict[str, DeltaAdversarialCase]:
        return {case.case_id: case for case in self.cases}

    def families(self) -> frozenset[str]:
        return frozenset(case.family for case in self.cases)

    def hard_negatives(self) -> tuple[DeltaAdversarialCase, ...]:
        return tuple(case for case in self.cases if case.hard_negative)

    def real_cases(self) -> tuple[DeltaAdversarialCase, ...]:
        return tuple(case for case in self.cases if case.kind == "real_public_source")


@dataclass(frozen=True)
class DeltaAdversarialPrediction:
    case_id: str
    equivalence: EquivalenceLabel
    revision_class: str
    same_event: bool


@dataclass(frozen=True)
class DeltaAdversarialReport:
    dataset_version: str
    split: str | None
    pair_count: int
    equivalence: BinaryMetricReport
    revision: RevisionMetricReport
    false_merge_count: int
    false_split_count: int
    uncertain_count: int


def load_delta_adversarial_gold(corpus_dir: Path) -> DeltaAdversarialCorpus:
    cases = (
        *_load_split_cases(corpus_dir / "pilot" / "cases.json"),
        *_load_split_cases(corpus_dir / "blind" / "cases.json"),
    )
    corpus = DeltaAdversarialCorpus(
        dataset_version=DATASET_VERSION,
        label_protocol_version=LABEL_PROTOCOL_VERSION,
        cases=cases,
    )
    validate_delta_adversarial_corpus(corpus)
    return corpus


def load_delta_adversarial_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be an object")
    return payload


def validate_delta_adversarial_corpus(corpus: DeltaAdversarialCorpus) -> None:
    if not corpus.cases:
        raise ValueError("corpus has no cases")
    case_ids = [case.case_id for case in corpus.cases]
    _assert_unique("case_id", case_ids)
    if corpus.dataset_version != DATASET_VERSION:
        raise ValueError("unexpected dataset_version")
    if corpus.label_protocol_version != LABEL_PROTOCOL_VERSION:
        raise ValueError("unexpected label_protocol_version")
    missing_families = set(REQUIRED_FAMILIES) - corpus.families()
    if missing_families:
        raise ValueError(f"corpus missing required families: {sorted(missing_families)}")
    for case in corpus.cases:
        _validate_case_labels(case)
    assert_split_partition(corpus)
    for split in ("pilot", "blind"):
        scoped = corpus.for_split(split)
        missing = set(REQUIRED_FAMILIES) - scoped.families()
        if missing:
            raise ValueError(f"{split} missing required families: {sorted(missing)}")


def assert_split_partition(corpus: DeltaAdversarialCorpus) -> None:
    groups: dict[str, dict[str, set[str]]] = {
        "pilot": {"case": set(), "bundle": set(), "event": set()},
        "blind": {"case": set(), "bundle": set(), "event": set()},
    }
    for case in corpus.cases:
        groups[case.split]["case"].add(case.case_id)
        groups[case.split]["bundle"].add(case.bundle_id)
        groups[case.split]["event"].add(case.prior_event_id)
        groups[case.split]["event"].add(case.candidate_event_id)
    for kind in ("case", "bundle", "event"):
        overlap = groups["pilot"][kind] & groups["blind"][kind]
        if overlap:
            raise ValueError(f"pilot/{kind} IDs overlap the held-out split: {sorted(overlap)[:8]}")


def scan_python_sources(root: Path, forbidden: Iterable[str]) -> tuple[str, ...]:
    tokens = tuple(token for token in forbidden if token)
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        hits = sorted(token for token in tokens if token in text)
        if hits:
            violations.append(f"{path}: {', '.join(hits)}")
    return tuple(violations)


def tokenize_claim_text(*parts: str) -> frozenset[str]:
    tokens: set[str] = set()
    for part in parts:
        tokens.update(token.casefold() for token in _TOKEN_RE.findall(part))
    return frozenset(tokens)


def token_jaccard(left: str, right: str) -> float:
    left_tokens = tokenize_claim_text(left)
    right_tokens = tokenize_claim_text(right)
    if not left_tokens and not right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def lexical_baseline_prediction(
    case: DeltaAdversarialCase,
    *,
    threshold: float = LEXICAL_JACCARD_THRESHOLD,
) -> DeltaAdversarialPrediction:
    overlap = token_jaccard(case.prior.text, case.candidate.text)
    equivalent = overlap >= threshold
    return DeltaAdversarialPrediction(
        case_id=case.case_id,
        equivalence="equivalent" if equivalent else "not_equivalent",
        revision_class="NON_NOVEL" if equivalent else "STATE_UPDATE",
        same_event=equivalent,
    )


def gold_oracle_prediction(case: DeltaAdversarialCase) -> DeltaAdversarialPrediction:
    return DeltaAdversarialPrediction(
        case_id=case.case_id,
        equivalence=case.equivalence,
        revision_class=case.revision_class,
        same_event=case.same_gold_event,
    )


def evaluate_delta_adversarial(
    corpus: DeltaAdversarialCorpus,
    predicted: Mapping[str, DeltaAdversarialPrediction],
    *,
    split: str | None = None,
) -> DeltaAdversarialReport:
    scoped = corpus.for_split(split) if split is not None else corpus
    missing = [case.case_id for case in scoped.cases if case.case_id not in predicted]
    if missing:
        raise ValueError(f"missing predictions for cases: {missing[:8]}")

    scored = tuple((case, predicted[case.case_id]) for case in scoped.cases)
    decided = tuple(
        (case, prediction)
        for case, prediction in scored
        if case.equivalence != "uncertain"
    )
    equivalence = binary_metrics(
        tuple(case.equivalence == "equivalent" for case, _ in decided),
        tuple(prediction.equivalence == "equivalent" for _, prediction in decided),
    )
    revision = revision_metrics(
        tuple(case.revision_class for case, _ in scored),
        tuple(prediction.revision_class for _, prediction in scored),
    )
    false_merge = 0
    false_split = 0
    for case, prediction in scored:
        if not case.same_gold_event and prediction.same_event:
            false_merge += 1
        elif case.same_gold_event and not prediction.same_event:
            false_split += 1
    return DeltaAdversarialReport(
        dataset_version=scoped.dataset_version,
        split=split,
        pair_count=len(scoped.cases),
        equivalence=equivalence,
        revision=revision,
        false_merge_count=false_merge,
        false_split_count=false_split,
        uncertain_count=sum(1 for case in scoped.cases if case.equivalence == "uncertain"),
    )


def _load_split_cases(path: Path) -> tuple[DeltaAdversarialCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} must be a JSON array")
    return tuple(_case_from_record(CaseRecord.model_validate(raw)) for raw in payload)


def _case_from_record(record: CaseRecord) -> DeltaAdversarialCase:
    return DeltaAdversarialCase(
        case_id=record.case_id,
        bundle_id=record.bundle_id,
        split=record.split,
        family=record.family,
        kind=record.kind,
        hard_negative=record.hard_negative,
        publisher=record.publisher,
        provenance_url=record.provenance_url,
        prior=DeltaAdversarialClaim(
            value=record.prior.value,
            detail=record.prior.detail,
            valid_at=record.prior.valid_at,
        ),
        candidate=DeltaAdversarialClaim(
            value=record.candidate.value,
            detail=record.candidate.detail,
            valid_at=record.candidate.valid_at,
        ),
        equivalence=record.equivalence,
        revision_class=record.revision_class,
        event_label=record.event_label,
        prior_event_id=record.prior_event_id,
        candidate_event_id=record.candidate_event_id,
        explicit_correction=record.explicit_correction,
        unresolved_source_conflict=record.unresolved_source_conflict,
        rationale=record.rationale,
    )


def _validate_case_labels(case: DeltaAdversarialCase) -> None:
    if case.kind == "real_public_source":
        if not case.provenance_url.startswith("https://"):
            raise ValueError(f"{case.case_id} real case is missing an https provenance URL")
    elif case.provenance_url.startswith("https://"):
        raise ValueError(f"{case.case_id} synthetic case must not count a live URL as real")

    if case.equivalence == "equivalent" and case.revision_class != "NON_NOVEL":
        raise ValueError(f"{case.case_id} equivalent pairs must be NON_NOVEL")
    if case.revision_class == "NON_NOVEL" and case.equivalence != "equivalent":
        raise ValueError(f"{case.case_id} NON_NOVEL pairs must be equivalent")
    if case.equivalence == "equivalent" and not case.same_gold_event:
        raise ValueError(f"{case.case_id} equivalent pairs must share Event identity")

    if case.revision_class == "CORRECTION" and not case.explicit_correction:
        raise ValueError(f"{case.case_id} CORRECTION requires explicit_correction")
    if case.revision_class == "UNRESOLVED_CONTRADICTION":
        if case.equivalence == "equivalent":
            raise ValueError(f"{case.case_id} unresolved contradiction cannot be equivalent")
    if case.revision_class == "STATE_UPDATE":
        if case.candidate.valid_at <= case.prior.valid_at:
            raise ValueError(f"{case.case_id} STATE_UPDATE requires a later candidate valid_at")
        if not case.same_gold_event:
            raise ValueError(f"{case.case_id} STATE_UPDATE must keep Event identity")
        if case.equivalence == "equivalent":
            raise ValueError(f"{case.case_id} STATE_UPDATE cannot be equivalent")
    if case.revision_class == "DETAIL":
        if not case.same_gold_event:
            raise ValueError(f"{case.case_id} DETAIL must keep Event identity")
        if case.equivalence == "equivalent":
            raise ValueError(f"{case.case_id} DETAIL adds information and is not equivalent")
    if case.revision_class == "NEW_FACT" and case.equivalence == "equivalent":
        raise ValueError(f"{case.case_id} NEW_FACT cannot be equivalent")


def _assert_unique(label: str, values: Sequence[str]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label} values")
