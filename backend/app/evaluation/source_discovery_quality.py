"""Deterministic source-discovery quality measurement.

This benchmark exercises the production topic-discovery path without adding
gold URLs as runtime hints.  Network acquisition is represented by small
recorded transport/extraction probes and is kept separate from live source
qualification.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.source_actionability import actionability_allows_approve
from app.services.source_catalog import SourceKind
from app.services.source_discovery import (
    SourceCandidate,
    discover_sources_for_topics,
    recommendation_can_subscribe,
)
from app.services.source_feed_discover import _sniff_feed_family
from app.services.source_registry import AuthorityStatus, SourceRegistry, canonicalize_url

DATASET_VERSION = "source-discovery-quality-v0.1"
MEASUREMENT_VERSION = "source-discovery-quality-measurement-v0.1"
SOURCE_DISCOVERY_VERSION = "source-discovery-v1"

AuthorityName = Literal["primary", "secondary", "discovery_only"]
LanguageName = Literal["en", "ja"]
ProbeStage = Literal["acquisition", "extraction"]
ProbeOutcomeName = Literal["covered", "acquisition_failed", "extraction_failed"]

REQUIRED_FAMILIES = (
    SourceKind.GITHUB_RELEASE.value,
    SourceKind.RSS_ATOM.value,
    SourceKind.GENERIC_WEB.value,
    SourceKind.GITHUB_ADVISORY.value,
    SourceKind.OSV.value,
    SourceKind.STATUSPAGE.value,
)
REQUIRED_FLOORS = {
    "primary_recall_at_20": 0.9,
    "relevant_recall_at_50": 0.85,
    "precision_at_20": 0.8,
    "japanese_recall_at_50": 0.85,
    "min_topic_primary_recall_at_20": 0.7,
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDiscoveryQualityCase(_StrictModel):
    case_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    family: str = Field(min_length=1)
    authority: AuthorityName
    language: LanguageName
    expected_discovered: bool = True
    expected_subscribable: bool = True
    rationale: str = Field(min_length=1)


class DeterministicProbe(_StrictModel):
    probe_id: str = Field(min_length=1)
    stage: ProbeStage
    status_code: int = Field(ge=100, le=599)
    content_type: str = Field(min_length=1)
    hinted_family: Literal["rss_atom", "json_feed"]
    body: str = Field(default="", max_length=1_000_000)
    fixture_reference: str = Field(min_length=1)
    expected_outcome: ProbeOutcomeName


class LiveQualificationReference(_StrictModel):
    status: Literal["separate"]
    artifact: str = Field(min_length=1)
    execution_mode: Literal["live_network"]
    included_in_metrics: Literal[False]


class SourceDiscoveryQualityCorpus(_StrictModel):
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    production_version: str = Field(min_length=1)
    split: Literal["dev"]
    execution_mode: Literal["deterministic_fixture"]
    blind_read: Literal[False]
    gold_injected: Literal[False]
    human_gold: Literal[False]
    label_source: str = Field(min_length=1)
    hint_scope: Literal["no_builtin_hints"]
    precision_k: int = Field(ge=1, le=80)
    recall_k: int = Field(ge=1, le=80)
    floors: dict[str, float]
    live_qualification: LiveQualificationReference
    cases: list[SourceDiscoveryQualityCase] = Field(min_length=1)
    probes: list[DeterministicProbe] = Field(min_length=1)


@dataclass(frozen=True)
class QualityCaseOutcome:
    case_id: str
    topic: str
    canonical_url: str
    family: str
    language: str
    expected_authority: str
    expected_discovered: bool
    observed_authority: str | None
    identity_match: bool
    authority_match: bool
    expected_subscribable: bool
    observed_subscribable: bool | None
    subscribability_match: bool | None
    found: bool
    rank: int | None
    candidate_family: str | None
    outcome: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProbeOutcome:
    probe_id: str
    stage: str
    fixture_reference: str
    outcome: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceDiscoveryQualityReport:
    dataset_version: str
    measurement_version: str
    production_version: str
    source_sha: str | None
    split: str
    execution_mode: str
    blind_read: bool
    gold_injected: bool
    human_gold: bool
    label_source: str
    hint_scope: str
    evaluation_status: str
    live_qualification: dict[str, Any]
    metrics: dict[str, float]
    by_topic: dict[str, dict[str, float | int]]
    by_family: dict[str, dict[str, float | int]]
    authority: dict[str, dict[str, float | int]]
    outcome_counts: dict[str, int]
    negative_outcome_counts: dict[str, int]
    failure_class_counts: dict[str, int]
    probe_outcomes: tuple[ProbeOutcome, ...]
    cases: tuple[QualityCaseOutcome, ...]
    floors: dict[str, float]
    violations: tuple[str, ...]
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_version": self.measurement_version,
            "dataset_version": self.dataset_version,
            "production_version": self.production_version,
            "source_sha": self.source_sha,
            "path": "production_discovery",
            "split": self.split,
            "execution_mode": self.execution_mode,
            "blind_read": self.blind_read,
            "gold_injected": self.gold_injected,
            "human_gold": self.human_gold,
            "label_source": self.label_source,
            "hint_scope": self.hint_scope,
            "evaluation_status": self.evaluation_status,
            "live_qualification": self.live_qualification,
            "case_count": len(self.cases),
            "topic_count": len(self.by_topic),
            "family_count": len(self.by_family),
            "metrics": self.metrics,
            "by_topic": self.by_topic,
            "by_family": self.by_family,
            "authority": self.authority,
            "outcome_counts": self.outcome_counts,
            "negative_outcome_counts": self.negative_outcome_counts,
            "failure_class_counts": self.failure_class_counts,
            "probe_outcomes": [row.as_dict() for row in self.probe_outcomes],
            "cases": [row.as_dict() for row in self.cases],
            "floors": self.floors,
            "violations": list(self.violations),
            "passed": self.passed,
        }


def load_source_discovery_quality_corpus(path: Path) -> SourceDiscoveryQualityCorpus:
    payload = json.loads(path.read_text(encoding="utf-8"))
    corpus = SourceDiscoveryQualityCorpus.model_validate(payload)
    validate_source_discovery_quality_corpus(corpus)
    return corpus


def validate_source_discovery_quality_corpus(
    corpus: SourceDiscoveryQualityCorpus,
) -> None:
    if corpus.dataset_version != DATASET_VERSION:
        raise ValueError(f"unsupported source-discovery quality version: {corpus.dataset_version}")
    if corpus.production_version != SOURCE_DISCOVERY_VERSION:
        raise ValueError("corpus production_version does not match source discovery")
    if corpus.recall_k < corpus.precision_k:
        raise ValueError("recall_k must be at least precision_k")
    if set(corpus.floors) != set(REQUIRED_FLOORS):
        raise ValueError("source-discovery quality floors are incomplete")
    for name, floor in REQUIRED_FLOORS.items():
        if float(corpus.floors[name]) < floor:
            raise ValueError(f"floor {name} was lowered below the established gate")

    ids = [case.case_id for case in corpus.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source-discovery quality case ids")
    topic_urls = []
    for case in corpus.cases:
        canonical = _canonical(case.canonical_url)
        if case.canonical_url != canonical:
            raise ValueError(f"case {case.case_id} is not canonicalized")
        topic_urls.append((case.topic, canonical))
    if len(topic_urls) != len(set(topic_urls)):
        raise ValueError("duplicate source-discovery quality topic URLs")
    families = {case.family for case in corpus.cases}
    unknown_families = families - {kind.value for kind in SourceKind}
    if unknown_families:
        raise ValueError(f"corpus has unknown source families: {sorted(unknown_families)}")
    missing_families = set(REQUIRED_FAMILIES) - families
    if missing_families:
        raise ValueError(f"corpus missing source families: {sorted(missing_families)}")
    authorities = {case.authority for case in corpus.cases}
    if authorities != {"primary", "secondary", "discovery_only"}:
        raise ValueError("corpus must distinguish primary, secondary, and discovery_only")
    if "ja" not in {case.language for case in corpus.cases}:
        raise ValueError("corpus must contain a Japanese segment")
    if not any(
        case.family in {SourceKind.GITHUB_ADVISORY.value, SourceKind.OSV.value}
        and not case.expected_subscribable
        for case in corpus.cases
    ):
        raise ValueError("corpus must contain a found-but-unsubscribable candidate")

    probe_ids = [probe.probe_id for probe in corpus.probes]
    if len(probe_ids) != len(set(probe_ids)):
        raise ValueError("duplicate deterministic probe ids")
    observed_by_id = {
        probe.probe_id: classify_deterministic_probe(probe) for probe in corpus.probes
    }
    mismatches = [
        probe.probe_id
        for probe in corpus.probes
        if observed_by_id[probe.probe_id] != probe.expected_outcome
    ]
    if mismatches:
        raise ValueError(
            "deterministic probe outcome mismatch: " + ", ".join(sorted(mismatches))
        )
    probe_outcomes = set(observed_by_id.values())
    if "acquisition_failed" not in probe_outcomes:
        raise ValueError("corpus must contain an acquisition failure probe")
    if "extraction_failed" not in probe_outcomes:
        raise ValueError("corpus must contain an extraction failure probe")
    if corpus.live_qualification.included_in_metrics is not False:
        raise ValueError("live qualification must stay outside deterministic metrics")


def classify_deterministic_probe(probe: DeterministicProbe) -> ProbeOutcomeName:
    """Classify a recorded probe without making a network request."""
    if probe.status_code >= 400:
        return "acquisition_failed"
    if probe.stage == "acquisition":
        return "covered"
    try:
        hinted = SourceKind(probe.hinted_family)
    except ValueError as exc:
        raise ValueError(f"unsupported probe family: {probe.hinted_family}") from exc
    sniffed = _sniff_feed_family(
        probe.content_type.split(";", 1)[0].strip().lower(),
        probe.body.encode("utf-8"),
        hinted,
    )
    return "covered" if sniffed == hinted else "extraction_failed"


def evaluate_source_discovery_quality(
    corpus: SourceDiscoveryQualityCorpus,
    *,
    registry: SourceRegistry | None = None,
    source_sha: str | None = None,
) -> SourceDiscoveryQualityReport:
    validate_source_discovery_quality_corpus(corpus)
    source_registry = registry or SourceRegistry()
    topics = sorted({case.topic for case in corpus.cases})
    results = {
        topic: discover_sources_for_topics(
            (topic,),
            source_registry,
            persist_registry=False,
            include_curated_seeds=False,
            include_builtin_hints=False,
            limit=corpus.recall_k,
        )
        for topic in topics
    }
    outcomes = tuple(
        _case_outcome(case, results[case.topic].items, corpus.recall_k)
        for case in corpus.cases
    )
    by_topic = _topic_metrics(corpus, results)
    by_family = _family_metrics(corpus, results)
    authority = _authority_metrics(corpus, outcomes, corpus.recall_k)
    metrics = _overall_metrics(corpus, results, outcomes)
    probe_outcomes = tuple(
        ProbeOutcome(
            probe_id=probe.probe_id,
            stage=probe.stage,
            fixture_reference=probe.fixture_reference,
            outcome=classify_deterministic_probe(probe),
        )
        for probe in corpus.probes
    )
    positive_outcomes = [row for row in outcomes if row.expected_discovered]
    negative_outcomes = [row for row in outcomes if not row.expected_discovered]
    outcome_counts = dict(sorted(Counter(row.outcome for row in positive_outcomes).items()))
    negative_outcome_counts = dict(
        sorted(Counter(row.outcome for row in negative_outcomes).items())
    )
    failures = Counter()
    for row in positive_outcomes:
        if row.outcome == "undiscovered":
            failures["undiscovered"] += 1
        elif row.outcome == "found_but_unsubscribable":
            failures["unsubscribable"] += 1
    failures.update(row.outcome for row in probe_outcomes if row.outcome != "covered")
    violations = list(_quality_violations(metrics, by_topic, corpus.floors))
    evaluation_status = (
        "scored" if any(results[topic].items for topic in topics) else "not_evaluable"
    )
    if evaluation_status == "not_evaluable":
        violations.append("evaluation_not_evaluable:no_independent_hints")
    return SourceDiscoveryQualityReport(
        dataset_version=corpus.dataset_version,
        measurement_version=MEASUREMENT_VERSION,
        production_version=corpus.production_version,
        source_sha=source_sha,
        split=corpus.split,
        execution_mode=corpus.execution_mode,
        blind_read=corpus.blind_read,
        gold_injected=corpus.gold_injected,
        human_gold=corpus.human_gold,
        label_source=corpus.label_source,
        hint_scope=corpus.hint_scope,
        evaluation_status=evaluation_status,
        live_qualification=corpus.live_qualification.model_dump(mode="json"),
        metrics=metrics,
        by_topic=by_topic,
        by_family=by_family,
        authority=authority,
        outcome_counts=outcome_counts,
        negative_outcome_counts=negative_outcome_counts,
        failure_class_counts=dict(sorted(failures.items())),
        probe_outcomes=probe_outcomes,
        cases=outcomes,
        floors=dict(sorted(corpus.floors.items())),
        violations=tuple(violations),
        passed=evaluation_status == "scored" and not violations,
    )


def source_discovery_quality_violations(
    report: SourceDiscoveryQualityReport,
    floors: Mapping[str, float] | None = None,
) -> tuple[str, ...]:
    return _quality_violations(
        report.metrics,
        report.by_topic,
        floors or report.floors,
    )


def _case_outcome(
    case: SourceDiscoveryQualityCase,
    items: tuple[SourceCandidate, ...],
    recall_k: int,
) -> QualityCaseOutcome:
    expected_url = _canonical(case.canonical_url)
    rank = None
    candidate = None
    for index, item in enumerate(items[:recall_k], start=1):
        if _canonical(item.canonical_url) == expected_url:
            rank = index
            candidate = item
            break
    identity_match = candidate is not None and candidate.family == case.family
    observed_authority = _observed_authority(candidate) if candidate is not None else None
    observed_subscribable = (
        recommendation_can_subscribe(candidate) if candidate is not None else None
    )
    authority_match = identity_match and observed_authority == case.authority
    subscribability_match = (
        observed_subscribable == case.expected_subscribable if identity_match else None
    )
    found = identity_match and authority_match and subscribability_match is True
    if not case.expected_discovered:
        outcome = "unexpectedly_found" if found else "not_expected"
    elif not found:
        if candidate is None:
            outcome = "undiscovered"
        elif not identity_match:
            outcome = "identity_mismatch"
        elif not authority_match:
            outcome = "authority_mismatch"
        else:
            outcome = "actionability_mismatch"
    elif not actionability_allows_approve(candidate.actionability):
        outcome = "found_but_unsubscribable"
    else:
        outcome = "found"
    return QualityCaseOutcome(
        case_id=case.case_id,
        topic=case.topic,
        canonical_url=expected_url,
        family=case.family,
        language=case.language,
        expected_authority=case.authority,
        expected_discovered=case.expected_discovered,
        observed_authority=observed_authority,
        identity_match=identity_match,
        authority_match=authority_match,
        expected_subscribable=case.expected_subscribable,
        observed_subscribable=observed_subscribable,
        subscribability_match=subscribability_match,
        found=found,
        rank=rank,
        candidate_family=candidate.family if candidate is not None else None,
        outcome=outcome,
    )


def _topic_metrics(
    corpus: SourceDiscoveryQualityCorpus,
    results: Mapping[str, Any],
) -> dict[str, dict[str, float | int]]:
    rows: dict[str, dict[str, float | int]] = {}
    for topic in sorted({case.topic for case in corpus.cases}):
        cases = [case for case in corpus.cases if case.topic == topic and case.expected_discovered]
        items = tuple(results[topic].items)
        top20 = items[: corpus.precision_k]
        top50 = items[: corpus.recall_k]
        hits20 = sum(any(_candidate_matches_case(item, case) for case in cases) for item in top20)
        hits50 = sum(any(_candidate_matches_case(item, case) for case in cases) for item in top50)
        primary = [case for case in cases if case.authority == "primary"]
        primary_hits = sum(
            any(_candidate_matches_case(item, case) for case in primary) for item in top20
        )
        rows[topic] = {
            "case_count": len(cases),
            "candidate_count": len(items),
            "predicted_count_at_20": len(top20),
            "relevant_hits_at_20": hits20,
            "precision_at_20": _ratio(hits20, corpus.precision_k),
            "relevant_hits_at_50": hits50,
            "relevant_recall_at_50": _ratio(hits50, len(cases)),
            "primary_count": len(primary),
            "primary_hits_at_20": primary_hits,
            "primary_recall_at_20": _ratio(primary_hits, len(primary)),
        }
    return rows


def _family_metrics(
    corpus: SourceDiscoveryQualityCorpus,
    results: Mapping[str, Any],
) -> dict[str, dict[str, float | int]]:
    rows: dict[str, dict[str, float | int]] = {}
    for family in sorted({case.family for case in corpus.cases}):
        cases = [
            case
            for case in corpus.cases
            if case.family == family and case.expected_discovered
        ]
        expected_by_topic = defaultdict(set)
        for case in cases:
            expected_by_topic[case.topic].add(case.case_id)
        predicted: list[SourceCandidate] = []
        for topic in expected_by_topic:
            predicted.extend(results[topic].items[: corpus.precision_k])
        hits20 = sum(
            item.family == family
            and any(
                _candidate_matches_case(item, case)
                for case in cases
                if case.topic == topic
            )
            for topic in expected_by_topic
            for item in results[topic].items[: corpus.precision_k]
        )
        predicted_family = [item for item in predicted if item.family == family]
        hits50 = sum(
            any(
                _candidate_matches_case(item, case)
                for case in cases
                if case.topic == topic
            )
            for topic in expected_by_topic
            for item in results[topic].items[: corpus.recall_k]
            if item.family == family
        )
        rows[family] = {
            "case_count": len(cases),
            "predicted_count_at_20": len(predicted_family),
            "relevant_hits_at_20": hits20,
            "precision_at_20": _ratio(
                hits20,
                len(expected_by_topic) * corpus.precision_k,
            ),
            "relevant_hits_at_50": hits50,
            "recall_at_50": _ratio(hits50, len(cases)),
        }
    return rows


def _authority_metrics(
    corpus: SourceDiscoveryQualityCorpus,
    outcomes: tuple[QualityCaseOutcome, ...],
    recall_k: int,
) -> dict[str, dict[str, float | int]]:
    rows: dict[str, dict[str, float | int]] = {}
    for authority in ("primary", "secondary", "discovery_only"):
        expected = [
            case
            for case in corpus.cases
            if case.expected_discovered and case.authority == authority
        ]
        found = [
            row
            for row in outcomes
            if row.expected_authority == authority
            and row.expected_discovered
            and row.rank is not None
            and row.rank <= recall_k
        ]
        observed = sum(
            row.expected_discovered and row.observed_authority == authority
            for row in outcomes
        )
        rows[authority] = {
            "expected_count": len(expected),
            "found_count_at_50": len(found),
            "recall_at_50": _ratio(len(found), len(expected)),
            "observed_count": observed,
            "authority_match_count": sum(
                row.authority_match
                for row in outcomes
                if row.expected_discovered and row.expected_authority == authority
            ),
        }
    return rows


def _overall_metrics(
    corpus: SourceDiscoveryQualityCorpus,
    results: Mapping[str, Any],
    outcomes: tuple[QualityCaseOutcome, ...],
) -> dict[str, float]:
    relevant = [case for case in corpus.cases if case.expected_discovered]
    total_predictions = 0
    relevant_hits20 = 0
    relevant_hits50 = 0
    primary_total = 0
    primary_hits20 = 0
    japanese_total = 0
    japanese_hits50 = 0
    for topic in sorted({case.topic for case in corpus.cases}):
        cases = [case for case in relevant if case.topic == topic]
        top20 = results[topic].items[: corpus.precision_k]
        top50 = results[topic].items[: corpus.recall_k]
        total_predictions += corpus.precision_k
        relevant_hits20 += sum(any(_candidate_matches_case(item, case) for case in cases) for item in top20)
        relevant_hits50 += sum(any(_candidate_matches_case(item, case) for case in cases) for item in top50)
        primary = [case for case in cases if case.authority == "primary"]
        japanese = [case for case in cases if case.language == "ja"]
        primary_total += len(primary)
        primary_hits20 += sum(any(_candidate_matches_case(item, case) for case in primary) for item in top20)
        japanese_total += len(japanese)
        japanese_hits50 += sum(
            any(_candidate_matches_case(item, case) for case in japanese)
            for item in top50
        )
    authority_matches = sum(
        row.authority_match
        for row in outcomes
        if row.expected_discovered and row.identity_match
    )
    found_count = sum(
        row.expected_discovered and row.identity_match
        for row in outcomes
    )
    return {
        "precision_at_20": _ratio(relevant_hits20, total_predictions),
        "relevant_recall_at_50": _ratio(relevant_hits50, len(relevant)),
        "primary_recall_at_20": _ratio(primary_hits20, primary_total),
        "japanese_recall_at_50": _ratio(japanese_hits50, japanese_total),
        "authority_match_rate": _ratio(authority_matches, found_count),
    }


def _quality_violations(
    metrics: Mapping[str, float],
    by_topic: Mapping[str, Mapping[str, float | int]],
    floors: Mapping[str, float],
) -> tuple[str, ...]:
    violations = [
        f"{name} {float(metrics.get(name, 0.0)):.3f} < {float(floor):.3f}"
        for name, floor in floors.items()
        if name != "min_topic_primary_recall_at_20"
        and float(metrics.get(name, 0.0)) < float(floor)
    ]
    topic_floor = float(floors.get("min_topic_primary_recall_at_20", 0.0))
    for topic, row in sorted(by_topic.items()):
        if row["primary_count"] and float(row["primary_recall_at_20"]) < topic_floor:
            violations.append(
                f"topic:{topic}:primary_recall_at_20 "
                f"{float(row['primary_recall_at_20']):.3f} < {topic_floor:.3f}"
            )
    return tuple(violations)


def _observed_authority(candidate: SourceCandidate) -> AuthorityName:
    if candidate.discovery_only:
        return "discovery_only"
    if candidate.authority_status == AuthorityStatus.AUTHORITATIVE.value:
        return "primary"
    return "secondary"


def _candidate_matches_case(
    candidate: SourceCandidate,
    case: SourceDiscoveryQualityCase,
) -> bool:
    return (
        case.expected_discovered
        and _canonical(candidate.canonical_url) == _canonical(case.canonical_url)
        and candidate.family == case.family
        and _observed_authority(candidate) == case.authority
        and recommendation_can_subscribe(candidate) == case.expected_subscribable
    )


def _canonical(url: str) -> str:
    return canonicalize_url(url)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
