"""Source-to-feed important-unknown recall (Eval-01 / #72).

Runs acquisition fixtures through knownness + suppression + ranking.
Blind labels stay in tests/ and are never imported by this module's defaults.
One aggregate score cannot hide unknown-but-hidden or false-merge misses.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.false_suppression import decide_suppression
from app.services.knowledge_evidence import (
    KnowledgeEvidence,
    derive_knowledge_state,
)
from app.services.multiobjective_ranker import RankerCandidate, rank_candidates

DATASET_VERSION = "e2e-unknown-recall-v0.1"
BENCHMARK_VERSION = "e2e-unknown-recall-benchmark-v0.1"
K_CARDS = 10
CATASTROPHIC_STAGES = frozenset({"unknown_but_hidden", "false_merge"})
SplitName = Literal["pilot", "blind"]
CohortName = Literal["cold_start", "history_rich"]
StageName = Literal[
    "ok",
    "discovery",
    "fetch",
    "extraction",
    "coreference",
    "revision",
    "knownness",
    "ranking",
    "unknown_but_hidden",
    "false_merge",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceInput(_Strict):
    kind: str
    provenance: str
    confidence: str
    source_id: str
    created_at: int = 1
    claim_id: str | None = None


class CaseRecord(_Strict):
    case_id: str = Field(min_length=1)
    split: SplitName
    cohort: CohortName
    bundle_id: str
    item_id: str
    event_id: str
    claim_id: str
    arrived_at: str
    source_family: str
    information_type: str
    importance_level: Literal["low", "medium", "high", "critical"]
    relation_level: Literal["direct", "adjacent", "reference"] = "direct"
    delta_type: str = "new_fact"
    discovered: bool
    fetched: bool
    extracted: bool
    coreference_label: str
    identity_confidence: str | None = None
    revision_class: str | None = None
    evidence: list[EvidenceInput] = Field(default_factory=list)
    gold_important_unknown: bool
    gold_should_surface: bool
    gold_false_merge_if_joined: bool = False


class CaseEval(_Strict):
    case_id: str
    cohort: CohortName
    split: SplitName
    stage: StageName
    surfaced: bool
    rank: int | None
    suppression: str
    knownness_state: str
    knownness_confidence: str
    gold_important_unknown: bool
    important_unknown_hit: bool
    unknown_but_hidden: bool
    known_but_reshown: bool
    false_merge_miss: bool


@dataclass(frozen=True)
class CohortMetrics:
    cohort: str
    case_count: int
    important_unknown_recall: float
    surfaced_precision: float
    unknown_but_hidden: int
    known_but_reshown: int
    false_merge_misses: int
    cards_to_first_important_unknown: float | None
    stage_counts: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class E2EReport:
    version: str
    dataset_version: str
    k: int
    overall: CohortMetrics
    by_cohort: dict[str, CohortMetrics]
    catastrophic: dict[str, int]
    cases: tuple[CaseEval, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "dataset_version": self.dataset_version,
            "k": self.k,
            "overall": self.overall.as_dict(),
            "by_cohort": {key: value.as_dict() for key, value in self.by_cohort.items()},
            "catastrophic": dict(self.catastrophic),
            "cases": [case.model_dump() for case in self.cases],
        }


def load_e2e_cases(path: Path) -> tuple[CaseRecord, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(CaseRecord.model_validate(item) for item in payload)


def evaluate_e2e_unknown_recall(
    cases: Sequence[CaseRecord],
    *,
    k: int = K_CARDS,
) -> E2EReport:
    evaluated = tuple(_evaluate_case(case, bundle=_bundle(cases), k=k) for case in cases)
    overall = _metrics("all", evaluated)
    by_cohort = {
        name: _metrics(name, [row for row in evaluated if row.cohort == name])
        for name in ("cold_start", "history_rich")
    }
    catastrophic = {
        "unknown_but_hidden": overall.unknown_but_hidden,
        "false_merge_misses": overall.false_merge_misses,
    }
    return E2EReport(
        version=BENCHMARK_VERSION,
        dataset_version=DATASET_VERSION,
        k=k,
        overall=overall,
        by_cohort=by_cohort,
        catastrophic=catastrophic,
        cases=evaluated,
    )


def e2e_release_gate_violations(
    report: E2EReport, *, require_recall: bool = True
) -> list[str]:
    violations: list[str] = []
    if report.overall.unknown_but_hidden:
        violations.append(f"unknown_but_hidden={report.overall.unknown_but_hidden} (hard gate)")
    if report.overall.false_merge_misses:
        violations.append(f"false_merge_misses={report.overall.false_merge_misses} (hard gate)")
    if require_recall and report.overall.important_unknown_recall < 0.7:
        violations.append(f"important_unknown_recall={report.overall.important_unknown_recall:.3f} < 0.70")
    return violations


def require_e2e_release_gate(report: E2EReport, *, require_recall: bool = True) -> None:
    violations = e2e_release_gate_violations(report, require_recall=require_recall)
    if violations:
        raise AssertionError("e2e unknown-recall gate failed: " + "; ".join(violations))


def _bundle(cases: Sequence[CaseRecord]) -> dict[str, list[CaseRecord]]:
    grouped: dict[str, list[CaseRecord]] = defaultdict(list)
    for case in cases:
        grouped[case.bundle_id].append(case)
    return grouped


def _evaluate_case(
    case: CaseRecord,
    *,
    bundle: dict[str, list[CaseRecord]],
    k: int,
) -> CaseEval:
    evidence = [
        KnowledgeEvidence(
            id=f"{case.case_id}-{index}",
            user_id=case.cohort,
            claim_id=row.claim_id or case.claim_id,
            event_id=case.event_id,
            delta_id=None,
            kind=row.kind,
            provenance=row.provenance,
            confidence=row.confidence,
            source_id=row.source_id,
            created_at=row.created_at,
        )
        for index, row in enumerate(case.evidence)
    ]
    derived = derive_knowledge_state(evidence)
    decision = decide_suppression(
        knowledge_state=derived.state,
        knowledge_confidence=derived.confidence,
        identity_label=case.coreference_label,
        identity_confidence=case.identity_confidence,
        equivalence_label=case.coreference_label,
        revision_class=case.revision_class,
        importance_level=case.importance_level,
    )
    ranked = rank_candidates(
        [
            RankerCandidate(
                item_id=item.item_id,
                event_id=item.event_id,
                redundancy_group=item.event_id,
                topic_key=item.information_type,
                relation_level=item.relation_level,
                importance_level=item.importance_level,
                knownness_state=derive_knowledge_state(
                    [
                        KnowledgeEvidence(
                            id=f"{item.case_id}-r{index}",
                            user_id=item.cohort,
                            claim_id=item.claim_id,
                            event_id=item.event_id,
                            delta_id=None,
                            kind=row.kind,
                            provenance=row.provenance,
                            confidence=row.confidence,
                            source_id=row.source_id,
                            created_at=row.created_at,
                        )
                        for index, row in enumerate(item.evidence)
                    ]
                ).state,
                knownness_confidence=derive_knowledge_state(
                    [
                        KnowledgeEvidence(
                            id=f"{item.case_id}-c{index}",
                            user_id=item.cohort,
                            claim_id=item.claim_id,
                            event_id=item.event_id,
                            delta_id=None,
                            kind=row.kind,
                            provenance=row.provenance,
                            confidence=row.confidence,
                            source_id=row.source_id,
                            created_at=row.created_at,
                        )
                        for index, row in enumerate(item.evidence)
                    ]
                ).confidence,
                delta_type=item.delta_type,
                source_type=item.source_family,
                updated_at=item.arrived_at,
            )
            for item in bundle[case.bundle_id]
            if item.discovered and item.fetched and item.extracted
        ]
    )
    order = [row.item_id for row in ranked if not row.hidden and row.visibility != "hide"]
    rank = order.index(case.item_id) + 1 if case.item_id in order else None
    acquired = case.discovered and case.fetched and case.extracted
    hidden = decision.action == "hide"
    surfaced = bool(acquired and not hidden and rank is not None and rank <= k)
    unknown_but_hidden = bool(case.gold_important_unknown and hidden)
    false_merge_miss = bool(
        case.gold_important_unknown
        and case.gold_false_merge_if_joined
        and case.coreference_label in {"same_target", "equivalent"}
        and hidden
    )
    known_but_reshown = bool(
        not case.gold_important_unknown and case.gold_should_surface is False and surfaced
    )
    stage = _stage(
        case,
        acquired=acquired,
        hidden=hidden,
        rank=rank,
        k=k,
        unknown_but_hidden=unknown_but_hidden,
        false_merge_miss=false_merge_miss,
    )
    return CaseEval(
        case_id=case.case_id,
        cohort=case.cohort,
        split=case.split,
        stage=stage,
        surfaced=surfaced,
        rank=rank,
        suppression=decision.action,
        knownness_state=derived.state,
        knownness_confidence=derived.confidence,
        gold_important_unknown=case.gold_important_unknown,
        important_unknown_hit=bool(case.gold_important_unknown and surfaced),
        unknown_but_hidden=unknown_but_hidden,
        known_but_reshown=known_but_reshown,
        false_merge_miss=false_merge_miss,
    )


def _stage(
    case: CaseRecord,
    *,
    acquired: bool,
    hidden: bool,
    rank: int | None,
    k: int,
    unknown_but_hidden: bool,
    false_merge_miss: bool,
) -> StageName:
    if unknown_but_hidden:
        return "unknown_but_hidden"
    if false_merge_miss:
        return "false_merge"
    if not case.discovered:
        return "discovery"
    if not case.fetched:
        return "fetch"
    if not case.extracted:
        return "extraction"
    if case.revision_class in {"CORRECTION", "UNRESOLVED_CONTRADICTION"} and not case.gold_should_surface:
        return "revision"
    if hidden and case.gold_important_unknown:
        return "knownness"
    if hidden and not case.gold_should_surface:
        return "ok"
    if acquired and rank is not None and rank > k:
        return "ranking"
    if acquired and rank is None:
        return "ranking"
    return "ok"


def _metrics(name: str, rows: Sequence[CaseEval]) -> CohortMetrics:
    intended = [row for row in rows if row.gold_important_unknown]
    hits = sum(1 for row in intended if row.important_unknown_hit)
    recall = (hits / len(intended)) if intended else 1.0
    surfaced = [row for row in rows if row.surfaced]
    precision = sum(1 for row in surfaced if row.gold_important_unknown) / len(surfaced) if surfaced else 1.0
    firsts = [row.rank for row in intended if row.important_unknown_hit and row.rank]
    stage_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        stage_counts[row.stage] += 1
    return CohortMetrics(
        cohort=name,
        case_count=len(rows),
        important_unknown_recall=recall,
        surfaced_precision=precision,
        unknown_but_hidden=sum(1 for row in rows if row.unknown_but_hidden),
        known_but_reshown=sum(1 for row in rows if row.known_but_reshown),
        false_merge_misses=sum(1 for row in rows if row.false_merge_miss),
        cards_to_first_important_unknown=(sum(firsts) / len(firsts)) if firsts else None,
        stage_counts=dict(stage_counts),
    )
