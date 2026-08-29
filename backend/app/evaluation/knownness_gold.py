from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.label_contract import (
    PROTOCOL_VERSION,
    AnnotationRecord,
    DatasetManifest,
    assert_not_blind_for_production_scoring,
    is_blind_split,
    load_annotations,
    load_dataset_manifest,
)
from app.evaluation.semantic_quality import BinaryMetricReport, binary_metrics
from app.services.knowledge_evidence import (
    KnowledgeEvidence,
    derive_knowledge_state,
    provenance_for_kind,
)
from app.services.viewport_exposure import is_meaningful_display

DATASET_VERSION = "knownness-v0.1"
LABEL_PROTOCOL_VERSION = PROTOCOL_VERSION
SAFETY_METRIC = "unknown_but_hidden"
REQUIRED_FAMILIES = (
    "never_seen",
    "delivered_not_displayed",
    "briefly_displayed",
    "meaningfully_displayed",
    "explicitly_read",
    "already_knew",
    "learned_now",
    "cross_source_restatement",
    "added_detail",
    "correction",
    "baseline_before_follow",
)
SOURCE_FAMILIES = (
    "github_release",
    "github_advisory",
    "osv",
    "statuspage",
    "rss_atom",
    "json_feed",
)
EVIDENCE_TYPES = (
    "none",
    "delivered",
    "displayed",
    "read",
    "already_knew",
    "learned_now",
    "baseline",
)
SplitName = Literal["pilot", "blind"]
KnownnessLabel = Literal["already_knew", "new"]
RelationName = Literal[
    "unseen",
    "same_fact",
    "equivalent_restatement",
    "added_detail",
    "correction",
    "new_fact",
]
EvidenceKind = Literal[
    "delivered",
    "displayed",
    "read",
    "already_knew",
    "learned_now",
    "baseline",
]
SourceFamily = Literal[
    "github_release",
    "github_advisory",
    "osv",
    "statuspage",
    "rss_atom",
    "json_feed",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRecord(_StrictModel):
    evidence_id: str = Field(min_length=1)
    kind: EvidenceKind
    provenance: str = Field(min_length=1)
    confidence: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    created_at: int
    claim_id: str | None = None
    event_id: str | None = None
    delta_id: str | None = None


class DisplayAttemptRecord(_StrictModel):
    dwell_ms: int | None = None
    visible_ratio: float | None = None
    detail_opened: bool = False


class CandidateRecord(_StrictModel):
    item_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    knowledge_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_family: SourceFamily
    publisher: str = Field(min_length=1)
    relation_to_prior: RelationName
    importance_level: Literal["low", "normal", "high", "critical"]
    prior_claim_id: str | None = None
    prior_knowledge_id: str | None = None


class CaseRecord(_StrictModel):
    case_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    split: SplitName
    family: Literal[
        "never_seen",
        "delivered_not_displayed",
        "briefly_displayed",
        "meaningfully_displayed",
        "explicitly_read",
        "already_knew",
        "learned_now",
        "cross_source_restatement",
        "added_detail",
        "correction",
        "baseline_before_follow",
    ]
    evidence_type: Literal[
        "none",
        "delivered",
        "displayed",
        "read",
        "already_knew",
        "learned_now",
        "baseline",
    ]
    source_family: SourceFamily
    user_id: str = Field(min_length=1)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    display_attempt: DisplayAttemptRecord | None = None
    candidate: CandidateRecord
    knownness: KnownnessLabel
    should_surface: bool
    is_novel_fact: bool
    is_correction: bool
    rationale: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    label_protocol_version: str
    dataset_version: str
    ambiguous: bool = False

    @model_validator(mode="after")
    def validate_correction_and_versions(self) -> CaseRecord:
        if self.dataset_version != DATASET_VERSION:
            raise ValueError(f"{self.case_id} has unexpected dataset_version")
        if self.label_protocol_version != LABEL_PROTOCOL_VERSION:
            raise ValueError(f"{self.case_id} has unexpected label_protocol_version")
        if self.is_correction and self.candidate.relation_to_prior != "correction":
            raise ValueError(f"{self.case_id} is_correction requires relation_to_prior=correction")
        if self.candidate.relation_to_prior == "correction" and not self.is_correction:
            raise ValueError(f"{self.case_id} correction relation must set is_correction")
        if self.source_family != self.candidate.source_family:
            raise ValueError(f"{self.case_id} source_family must match candidate")
        return self


@dataclass(frozen=True)
class KnownnessGoldCase:
    case_id: str
    bundle_id: str
    split: SplitName
    family: str
    evidence_type: str
    user_id: str
    evidence: tuple[EvidenceRecord, ...]
    display_attempt: DisplayAttemptRecord | None
    candidate: CandidateRecord
    knownness: KnownnessLabel
    should_surface: bool
    is_novel_fact: bool
    is_correction: bool
    rationale: str
    provenance: str
    label_protocol_version: str
    dataset_version: str
    ambiguous: bool

    @property
    def source_family(self) -> str:
        return self.candidate.source_family

    @property
    def gold_known(self) -> bool:
        return self.knownness == "already_knew"

    @property
    def gold_unknown_should_surface(self) -> bool:
        return self.knownness == "new" and self.should_surface

    @property
    def gold_known_should_hide(self) -> bool:
        return self.knownness == "already_knew" and not self.should_surface


@dataclass(frozen=True)
class KnownnessGoldCorpus:
    dataset_version: str
    label_protocol_version: str
    cases: tuple[KnownnessGoldCase, ...]

    def for_split(self, split: str) -> KnownnessGoldCorpus:
        return KnownnessGoldCorpus(
            dataset_version=self.dataset_version,
            label_protocol_version=self.label_protocol_version,
            cases=tuple(case for case in self.cases if case.split == split),
        )

    def case_by_id(self) -> dict[str, KnownnessGoldCase]:
        return {case.case_id: case for case in self.cases}

    def families(self) -> frozenset[str]:
        return frozenset(case.family for case in self.cases)

    def source_families(self) -> frozenset[str]:
        return frozenset(case.source_family for case in self.cases)

    def evidence_types(self) -> frozenset[str]:
        return frozenset(case.evidence_type for case in self.cases)

    def scorable(self, *, include_ambiguous: bool) -> tuple[KnownnessGoldCase, ...]:
        if include_ambiguous:
            return self.cases
        return tuple(case for case in self.cases if not case.ambiguous)


@dataclass(frozen=True)
class KnownnessPrediction:
    case_id: str
    predicted_known: bool
    predicted_surface: bool
    predicted_novel_fact: bool
    predicted_correction: bool = False


@dataclass(frozen=True)
class SegmentMetrics:
    segment_key: str
    case_count: int
    known: BinaryMetricReport
    novel_fact: BinaryMetricReport
    known_but_reshown_rate: float
    unknown_but_hidden_rate: float
    correction_recall: float


@dataclass(frozen=True)
class KnownnessMetrics:
    case_count: int
    known: BinaryMetricReport
    novel_fact: BinaryMetricReport
    known_but_reshown_rate: float
    unknown_but_hidden_rate: float
    correction_recall: float
    by_evidence_type: tuple[SegmentMetrics, ...]
    by_source_family: tuple[SegmentMetrics, ...]


@dataclass(frozen=True)
class KnownnessEvaluationReport:
    dataset_version: str
    split: str | None
    safety_metric: str
    include_ambiguous: KnownnessMetrics
    exclude_ambiguous: KnownnessMetrics
    unresolved_ambiguous_count: int

    @property
    def unknown_but_hidden_rate(self) -> float:
        return self.exclude_ambiguous.unknown_but_hidden_rate

    @property
    def known_but_reshown_rate(self) -> float:
        return self.exclude_ambiguous.known_but_reshown_rate

    @property
    def correction_recall(self) -> float:
        return self.exclude_ambiguous.correction_recall


@dataclass(frozen=True)
class KnownnessReleaseGate:
    """Safety-first gate. Repetition gains cannot buy extra false suppression."""

    max_unknown_but_hidden_rate: float = 0.0
    min_correction_recall: float = 1.0
    max_known_but_reshown_rate: float = 1.0
    min_known_recall: float = 0.0
    min_novel_fact_recall: float = 0.0


DEFAULT_KNOWNNESS_RELEASE_GATE = KnownnessReleaseGate()


def load_knownness_gold(corpus_dir: Path) -> KnownnessGoldCorpus:
    cases = (
        *_load_split_cases(corpus_dir / "pilot" / "cases.json"),
        *_load_split_cases(corpus_dir / "blind" / "cases.json"),
    )
    corpus = KnownnessGoldCorpus(
        dataset_version=DATASET_VERSION,
        label_protocol_version=LABEL_PROTOCOL_VERSION,
        cases=cases,
    )
    validate_knownness_corpus(corpus)
    return corpus


def load_knownness_gold_for_production_scoring(corpus_dir: Path) -> KnownnessGoldCorpus:
    pilot_path = corpus_dir / "pilot" / "cases.json"
    if is_blind_split(path=pilot_path):
        raise ValueError("split=blind records must not be imported by production scoring code")
    cases = _load_split_cases(pilot_path)
    if any(case.split != "pilot" for case in cases):
        raise ValueError("production scoring may load the pilot split only")
    corpus = KnownnessGoldCorpus(
        dataset_version=DATASET_VERSION,
        label_protocol_version=LABEL_PROTOCOL_VERSION,
        cases=cases,
    )
    validate_knownness_corpus(corpus, require_both_splits=False)
    return corpus


def load_knownness_manifest(manifest_path: Path) -> DatasetManifest:
    return load_dataset_manifest(manifest_path)


def load_knownness_annotations(path: Path) -> tuple[AnnotationRecord, ...]:
    return load_annotations(path)


def load_knownness_annotations_for_production_scoring(path: Path) -> tuple[AnnotationRecord, ...]:
    records = load_annotations(path)
    assert_not_blind_for_production_scoring(records, path=path)
    return records


def validate_knownness_corpus(
    corpus: KnownnessGoldCorpus,
    *,
    require_both_splits: bool = True,
) -> None:
    if not corpus.cases:
        raise ValueError("corpus has no cases")
    if corpus.dataset_version != DATASET_VERSION:
        raise ValueError("unexpected dataset_version")
    if corpus.label_protocol_version != LABEL_PROTOCOL_VERSION:
        raise ValueError("unexpected label_protocol_version")
    _assert_unique("case_id", [case.case_id for case in corpus.cases])
    _assert_unique("item_id", [case.candidate.item_id for case in corpus.cases])
    missing = set(REQUIRED_FAMILIES) - corpus.families()
    if missing:
        raise ValueError(f"corpus missing required families: {sorted(missing)}")
    for case in corpus.cases:
        _validate_case_labels(case)
    assert_split_partition(corpus)
    if require_both_splits:
        for split in ("pilot", "blind"):
            scoped = corpus.for_split(split)
            gap = set(REQUIRED_FAMILIES) - scoped.families()
            if gap:
                raise ValueError(f"{split} missing required families: {sorted(gap)}")


def assert_split_partition(corpus: KnownnessGoldCorpus) -> None:
    groups: dict[str, dict[str, set[str]]] = {
        "pilot": {"case": set(), "bundle": set(), "user": set(), "item": set(), "event": set()},
        "blind": {"case": set(), "bundle": set(), "user": set(), "item": set(), "event": set()},
    }
    for case in corpus.cases:
        groups[case.split]["case"].add(case.case_id)
        groups[case.split]["bundle"].add(case.bundle_id)
        groups[case.split]["user"].add(case.user_id)
        groups[case.split]["item"].add(case.candidate.item_id)
        groups[case.split]["event"].add(case.candidate.event_id)
    for kind in ("case", "bundle", "user", "item", "event"):
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


def replay_case_evidence(case: KnownnessGoldCase) -> tuple[KnowledgeEvidence, ...]:
    """Replay the recorded evidence history. Display attempts are not invented."""
    return tuple(
        KnowledgeEvidence(
            id=row.evidence_id,
            user_id=case.user_id,
            claim_id=row.claim_id,
            event_id=row.event_id,
            delta_id=row.delta_id,
            kind=row.kind,
            provenance=row.provenance or provenance_for_kind(row.kind),
            confidence=row.confidence,
            source_id=row.source_id,
            created_at=row.created_at,
        )
        for row in case.evidence
    )


def replay_derived_knowledge(case: KnownnessGoldCase):
    return derive_knowledge_state(replay_case_evidence(case))


def display_attempt_is_meaningful(case: KnownnessGoldCase) -> bool | None:
    if case.display_attempt is None:
        return None
    return is_meaningful_display(
        dwell_ms=case.display_attempt.dwell_ms,
        visible_ratio=case.display_attempt.visible_ratio,
        detail_opened=case.display_attempt.detail_opened,
    )


def gold_oracle_prediction(case: KnownnessGoldCase) -> KnownnessPrediction:
    return KnownnessPrediction(
        case_id=case.case_id,
        predicted_known=case.gold_known,
        predicted_surface=case.should_surface,
        predicted_novel_fact=case.is_novel_fact,
        predicted_correction=case.is_correction,
    )


def delivery_is_known_prediction(case: KnownnessGoldCase) -> KnownnessPrediction:
    """Repetition-seeking baseline: any delivery or brief flash counts as known.

    This improves known-but-reshown by hiding delivered-not-displayed and
    briefly displayed items, which raises unknown-but-hidden.
    """
    kinds = {row.kind for row in case.evidence}
    seen = bool(kinds) or case.display_attempt is not None
    return KnownnessPrediction(
        case_id=case.case_id,
        predicted_known=seen,
        predicted_surface=not seen,
        predicted_novel_fact=not seen,
        predicted_correction=False,
    )


def show_all_prediction(case: KnownnessGoldCase) -> KnownnessPrediction:
    return KnownnessPrediction(
        case_id=case.case_id,
        predicted_known=False,
        predicted_surface=True,
        predicted_novel_fact=True,
        predicted_correction=case.candidate.relation_to_prior == "correction",
    )


def evaluate_knownness(
    corpus: KnownnessGoldCorpus,
    predicted: Mapping[str, KnownnessPrediction],
    *,
    split: str | None = None,
) -> KnownnessEvaluationReport:
    scoped = corpus.for_split(split) if split is not None else corpus
    missing = [case.case_id for case in scoped.cases if case.case_id not in predicted]
    if missing:
        raise ValueError(f"missing predictions for cases: {missing[:8]}")
    include = _metrics_for_cases(scoped.scorable(include_ambiguous=True), predicted)
    exclude = _metrics_for_cases(scoped.scorable(include_ambiguous=False), predicted)
    unresolved = sum(1 for case in scoped.cases if case.ambiguous)
    return KnownnessEvaluationReport(
        dataset_version=scoped.dataset_version,
        split=split,
        safety_metric=SAFETY_METRIC,
        include_ambiguous=include,
        exclude_ambiguous=exclude,
        unresolved_ambiguous_count=unresolved,
    )


def knownness_release_gate_violations(
    report: KnownnessEvaluationReport,
    thresholds: KnownnessReleaseGate = DEFAULT_KNOWNNESS_RELEASE_GATE,
) -> tuple[str, ...]:
    metrics = report.exclude_ambiguous
    violations: list[str] = []
    if metrics.unknown_but_hidden_rate > thresholds.max_unknown_but_hidden_rate:
        violations.append(
            f"unknown_but_hidden_rate {metrics.unknown_but_hidden_rate:.3f} > "
            f"{thresholds.max_unknown_but_hidden_rate:.3f}"
        )
    if metrics.correction_recall < thresholds.min_correction_recall:
        violations.append(
            f"correction_recall {metrics.correction_recall:.3f} < {thresholds.min_correction_recall:.3f}"
        )
    if metrics.known.recall < thresholds.min_known_recall:
        violations.append(
            f"known_recall {metrics.known.recall:.3f} < {thresholds.min_known_recall:.3f}"
        )
    if metrics.novel_fact.recall < thresholds.min_novel_fact_recall:
        violations.append(
            f"novel_fact_recall {metrics.novel_fact.recall:.3f} < "
            f"{thresholds.min_novel_fact_recall:.3f}"
        )
    if metrics.known_but_reshown_rate > thresholds.max_known_but_reshown_rate:
        violations.append(
            f"known_but_reshown_rate {metrics.known_but_reshown_rate:.3f} > "
            f"{thresholds.max_known_but_reshown_rate:.3f}"
        )
    return tuple(violations)


def require_knownness_release_gate(
    report: KnownnessEvaluationReport,
    thresholds: KnownnessReleaseGate = DEFAULT_KNOWNNESS_RELEASE_GATE,
) -> None:
    violations = knownness_release_gate_violations(report, thresholds)
    if violations:
        raise AssertionError("knownness Gold failed release gate: " + "; ".join(violations))


def _metrics_for_cases(
    cases: Sequence[KnownnessGoldCase],
    predicted: Mapping[str, KnownnessPrediction],
) -> KnownnessMetrics:
    scored = tuple((case, predicted[case.case_id]) for case in cases)
    return KnownnessMetrics(
        case_count=len(cases),
        known=_known_metrics(scored),
        novel_fact=_novel_metrics(scored),
        known_but_reshown_rate=_known_but_reshown_rate(scored),
        unknown_but_hidden_rate=_unknown_but_hidden_rate(scored),
        correction_recall=_correction_recall(scored),
        by_evidence_type=_segment_metrics(scored, "evidence_type", lambda case: case.evidence_type),
        by_source_family=_segment_metrics(scored, "source_family", lambda case: case.source_family),
    )


def _known_metrics(
    scored: Sequence[tuple[KnownnessGoldCase, KnownnessPrediction]],
) -> BinaryMetricReport:
    return binary_metrics(
        tuple(case.gold_known for case, _ in scored),
        tuple(prediction.predicted_known for _, prediction in scored),
    )


def _novel_metrics(
    scored: Sequence[tuple[KnownnessGoldCase, KnownnessPrediction]],
) -> BinaryMetricReport:
    return binary_metrics(
        tuple(case.is_novel_fact for case, _ in scored),
        tuple(prediction.predicted_novel_fact for _, prediction in scored),
    )


def _known_but_reshown_rate(
    scored: Sequence[tuple[KnownnessGoldCase, KnownnessPrediction]],
) -> float:
    eligible = tuple(
        (case, prediction) for case, prediction in scored if case.gold_known_should_hide
    )
    if not eligible:
        return 0.0
    reshown = sum(1 for _, prediction in eligible if prediction.predicted_surface)
    return reshown / len(eligible)


def _unknown_but_hidden_rate(
    scored: Sequence[tuple[KnownnessGoldCase, KnownnessPrediction]],
) -> float:
    eligible = tuple(
        (case, prediction) for case, prediction in scored if case.gold_unknown_should_surface
    )
    if not eligible:
        return 0.0
    hidden = sum(1 for _, prediction in eligible if not prediction.predicted_surface)
    return hidden / len(eligible)


def _correction_recall(
    scored: Sequence[tuple[KnownnessGoldCase, KnownnessPrediction]],
) -> float:
    eligible = tuple((case, prediction) for case, prediction in scored if case.is_correction)
    if not eligible:
        return 1.0
    surfaced = sum(1 for _, prediction in eligible if prediction.predicted_surface)
    return surfaced / len(eligible)


def _segment_metrics(
    scored: Sequence[tuple[KnownnessGoldCase, KnownnessPrediction]],
    prefix: str,
    key_fn,
) -> tuple[SegmentMetrics, ...]:
    grouped: dict[str, list[tuple[KnownnessGoldCase, KnownnessPrediction]]] = defaultdict(list)
    for case, prediction in scored:
        grouped[f"{prefix}={key_fn(case)}"].append((case, prediction))
    rows: list[SegmentMetrics] = []
    for key in sorted(grouped):
        subset = tuple(grouped[key])
        rows.append(
            SegmentMetrics(
                segment_key=key,
                case_count=len(subset),
                known=_known_metrics(subset),
                novel_fact=_novel_metrics(subset),
                known_but_reshown_rate=_known_but_reshown_rate(subset),
                unknown_but_hidden_rate=_unknown_but_hidden_rate(subset),
                correction_recall=_correction_recall(subset),
            )
        )
    return tuple(rows)


def _load_split_cases(path: Path) -> tuple[KnownnessGoldCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} must be a JSON array")
    return tuple(_case_from_record(CaseRecord.model_validate(raw)) for raw in payload)


def _case_from_record(record: CaseRecord) -> KnownnessGoldCase:
    return KnownnessGoldCase(
        case_id=record.case_id,
        bundle_id=record.bundle_id,
        split=record.split,
        family=record.family,
        evidence_type=record.evidence_type,
        user_id=record.user_id,
        evidence=tuple(record.evidence),
        display_attempt=record.display_attempt,
        candidate=record.candidate,
        knownness=record.knownness,
        should_surface=record.should_surface,
        is_novel_fact=record.is_novel_fact,
        is_correction=record.is_correction,
        rationale=record.rationale,
        provenance=record.provenance,
        label_protocol_version=record.label_protocol_version,
        dataset_version=record.dataset_version,
        ambiguous=record.ambiguous,
    )


def _validate_case_labels(case: KnownnessGoldCase) -> None:
    if case.family == "never_seen":
        if case.evidence:
            raise ValueError(f"{case.case_id} never_seen must have empty evidence")
        if case.knownness != "new" or not case.should_surface:
            raise ValueError(f"{case.case_id} never_seen must be new and surfaced")
    if case.family == "delivered_not_displayed":
        if {row.kind for row in case.evidence} != {"delivered"}:
            raise ValueError(f"{case.case_id} delivered_not_displayed must record only delivered")
        if case.knownness != "new" or not case.should_surface:
            raise ValueError(f"{case.case_id} delivered-not-displayed remains unknown")
    if case.family == "briefly_displayed":
        if case.display_attempt is None:
            raise ValueError(f"{case.case_id} briefly_displayed requires a display_attempt")
        if display_attempt_is_meaningful(case):
            raise ValueError(f"{case.case_id} brief display must fail viewport-exposure-v1")
        if case.knownness != "new" or not case.should_surface:
            raise ValueError(f"{case.case_id} brief display remains unknown")
    if case.family == "meaningfully_displayed":
        if "displayed" not in {row.kind for row in case.evidence}:
            raise ValueError(f"{case.case_id} meaningfully_displayed requires KIND_DISPLAYED")
        if case.display_attempt is not None and not display_attempt_is_meaningful(case):
            raise ValueError(f"{case.case_id} meaningful display must pass viewport-exposure-v1")
        if case.knownness != "already_knew" or case.should_surface:
            raise ValueError(f"{case.case_id} meaningful same-fact reshown must be hidden")
    if case.family == "explicitly_read":
        if "read" not in {row.kind for row in case.evidence}:
            raise ValueError(f"{case.case_id} explicitly_read requires KIND_READ")
        if case.knownness != "already_knew" or case.should_surface:
            raise ValueError(f"{case.case_id} read same-fact reshown must be hidden")
    if case.family == "already_knew":
        if "already_knew" not in {row.kind for row in case.evidence}:
            raise ValueError(f"{case.case_id} already_knew requires explicit feedback")
        if case.knownness != "already_knew" or case.should_surface:
            raise ValueError(f"{case.case_id} explicit already_knew same-fact must be hidden")
    if case.family == "learned_now":
        if "learned_now" not in {row.kind for row in case.evidence}:
            raise ValueError(f"{case.case_id} learned_now requires explicit feedback")
        if case.knownness != "already_knew" or case.should_surface:
            raise ValueError(f"{case.case_id} learned_now same-fact must be hidden")
    if case.family == "cross_source_restatement":
        if case.candidate.relation_to_prior != "equivalent_restatement":
            raise ValueError(f"{case.case_id} cross-source case must be equivalent_restatement")
        if case.candidate.prior_knowledge_id != case.candidate.knowledge_id:
            raise ValueError(f"{case.case_id} restatement must share knowledge_id")
        if case.knownness != "already_knew" or case.should_surface:
            raise ValueError(f"{case.case_id} equivalent restatement must not reshown")
    if case.family == "added_detail":
        if case.candidate.relation_to_prior != "added_detail":
            raise ValueError(f"{case.case_id} added_detail relation mismatch")
        if case.candidate.knowledge_id == case.candidate.prior_knowledge_id:
            raise ValueError(f"{case.case_id} added detail must be a new knowledge target")
        if case.knownness != "new" or not case.should_surface or not case.is_novel_fact:
            raise ValueError(f"{case.case_id} added detail remains novel-to-user")
    if case.family == "correction":
        if not case.is_correction or not case.should_surface:
            raise ValueError(f"{case.case_id} correction must surface across the knownness boundary")
        if case.knownness != "already_knew":
            raise ValueError(f"{case.case_id} correction updates a known wrong fact")
    if case.family == "baseline_before_follow":
        if "baseline" not in {row.kind for row in case.evidence}:
            raise ValueError(f"{case.case_id} baseline_before_follow requires KIND_BASELINE")
        if case.knownness != "already_knew" or case.should_surface:
            raise ValueError(f"{case.case_id} follow baseline history must not flood the feed")
    if case.ambiguous and case.family not in {"never_seen", "briefly_displayed"}:
        raise ValueError(f"{case.case_id} ambiguous fixture must stay in an unknown-leaning family")


def _assert_unique(label: str, values: Sequence[str]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label} values")


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload
