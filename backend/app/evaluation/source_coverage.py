"""Topic × information-type source coverage benchmark (Source-09 / #65).

Measures which authoritative source classes the current catalog and static
acquisition path cover. Dynamic/JS-only pages are recorded as static coverage
gaps that justify later bounded rendering (#64). This module does not render
JavaScript and does not fetch the live network.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from app.services.source_catalog import MVP_SOURCE_POLICIES, SourceKind, get_source_policy
from app.services.source_registry import SourceRegistry, canonicalize_url

DATASET_VERSION = "source-coverage-v0.1"
LABEL_PROTOCOL_VERSION = "source-coverage-label-v1"
BENCHMARK_VERSION = "source-coverage-benchmark-v0.1"

SOURCE_FAMILIES = (
    "github",
    "statuspage",
    "rss_atom",
    "json_feed",
    "static_web",
    "dynamic_web",
)
INFORMATION_TYPES = (
    "release",
    "security",
    "incident",
    "pricing",
    "api_docs",
    "deprecation",
    "policy",
    "roadmap_changelog",
)
SplitName = Literal["pilot", "blind"]
AuthorityName = Literal["primary", "secondary"]
SourceFamilyName = Literal[
    "github",
    "statuspage",
    "rss_atom",
    "json_feed",
    "static_web",
    "dynamic_web",
]
InformationTypeName = Literal[
    "release",
    "security",
    "incident",
    "pricing",
    "api_docs",
    "deprecation",
    "policy",
    "roadmap_changelog",
]
OutcomeName = Literal[
    "covered",
    "not_discovered",
    "discovered_fetch_failed",
    "fetched_change_missed",
    "static_coverage_gap",
]

# First-class adapters can acquire without a per-URL registry row.
_FIRST_CLASS_FAMILIES = frozenset(
    {
        "github_release",
        "github_sbom",
        "osv",
        "github_advisory",
        "rss_atom",
        "json_feed",
        "statuspage",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoverageCaseRecord(_StrictModel):
    case_id: str = Field(min_length=1)
    split: SplitName
    topic: str = Field(min_length=1)
    ecosystem: str = Field(min_length=1)
    information_type: InformationTypeName
    source_family: SourceFamilyName
    catalog_family: str = Field(min_length=1)
    authority: AuthorityName
    canonical_url: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    expected_discovered: bool
    js_required: bool = False
    fetch_ok: bool = True
    update_expected: bool = True
    update_detectable_statically: bool = True
    delay_seconds: int = Field(ge=0, default=0)
    duplicate_group: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


@dataclass(frozen=True)
class CoverageCase:
    case_id: str
    split: SplitName
    topic: str
    ecosystem: str
    information_type: str
    source_family: str
    catalog_family: str
    authority: str
    canonical_url: str
    publisher: str
    provenance: str
    expected_discovered: bool
    js_required: bool
    fetch_ok: bool
    update_expected: bool
    update_detectable_statically: bool
    delay_seconds: int
    duplicate_group: str
    rationale: str

    @property
    def expected_authoritative(self) -> bool:
        return self.authority == "primary"


@dataclass(frozen=True)
class CoverageCorpus:
    dataset_version: str
    label_protocol_version: str
    cases: tuple[CoverageCase, ...]

    def for_split(self, split: str) -> CoverageCorpus:
        return CoverageCorpus(
            dataset_version=self.dataset_version,
            label_protocol_version=self.label_protocol_version,
            cases=tuple(case for case in self.cases if case.split == split),
        )

    def information_types(self) -> frozenset[str]:
        return frozenset(case.information_type for case in self.cases)

    def source_families(self) -> frozenset[str]:
        return frozenset(case.source_family for case in self.cases)


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    discovered: bool
    authoritative_predicted: bool
    acquired: bool
    update_detected: bool
    outcome: OutcomeName
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SegmentMetrics:
    key: str
    case_count: int
    discovery_recall: float
    authoritative_precision: float
    acquisition_success_rate: float
    update_detection_recall: float
    static_coverage_gap_rate: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceCoverageReport:
    dataset_version: str
    benchmark_version: str
    split: str | None
    case_count: int
    discovery_recall: float
    authoritative_source_precision: float
    acquisition_success_rate: float
    update_detection_recall: float
    median_acquisition_delay_seconds: float
    duplicate_source_rate: float
    static_coverage_gap_rate: float
    outcome_counts: dict[str, int]
    by_source_family: tuple[SegmentMetrics, ...]
    by_information_type: tuple[SegmentMetrics, ...]
    by_topic: tuple[SegmentMetrics, ...]
    cases: tuple[CaseOutcome, ...]
    js_rendering_implemented: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version,
            "benchmark_version": self.benchmark_version,
            "split": self.split,
            "case_count": self.case_count,
            "discovery_recall": self.discovery_recall,
            "authoritative_source_precision": self.authoritative_source_precision,
            "acquisition_success_rate": self.acquisition_success_rate,
            "update_detection_recall": self.update_detection_recall,
            "median_acquisition_delay_seconds": self.median_acquisition_delay_seconds,
            "duplicate_source_rate": self.duplicate_source_rate,
            "static_coverage_gap_rate": self.static_coverage_gap_rate,
            "outcome_counts": self.outcome_counts,
            "by_source_family": [row.as_dict() for row in self.by_source_family],
            "by_information_type": [row.as_dict() for row in self.by_information_type],
            "by_topic": [row.as_dict() for row in self.by_topic],
            "cases": [row.as_dict() for row in self.cases],
            "js_rendering_implemented": self.js_rendering_implemented,
        }


def load_source_coverage_gold(corpus_dir: Path) -> CoverageCorpus:
    cases = (
        *_load_split_cases(corpus_dir / "pilot" / "cases.json"),
        *_load_split_cases(corpus_dir / "blind" / "cases.json"),
    )
    corpus = CoverageCorpus(
        dataset_version=DATASET_VERSION,
        label_protocol_version=LABEL_PROTOCOL_VERSION,
        cases=cases,
    )
    validate_source_coverage_corpus(corpus)
    return corpus


def validate_source_coverage_corpus(corpus: CoverageCorpus) -> None:
    if not corpus.cases:
        raise ValueError("coverage corpus has no cases")
    ids = [case.case_id for case in corpus.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate coverage case ids")
    missing_types = set(INFORMATION_TYPES) - corpus.information_types()
    if missing_types:
        raise ValueError(f"corpus missing information types: {sorted(missing_types)}")
    missing_families = set(SOURCE_FAMILIES) - corpus.source_families()
    if missing_families:
        raise ValueError(f"corpus missing source families: {sorted(missing_families)}")
    for split in ("pilot", "blind"):
        scoped = corpus.for_split(split)
        missing = set(INFORMATION_TYPES) - scoped.information_types()
        if missing:
            raise ValueError(f"{split} missing information types: {sorted(missing)}")
        missing_fam = set(SOURCE_FAMILIES) - scoped.source_families()
        if missing_fam:
            raise ValueError(f"{split} missing source families: {sorted(missing_fam)}")
        if not any(case.authority == "primary" and case.provenance for case in scoped.cases):
            raise ValueError(f"{split} needs primary sources with provenance")
        if not any(case.js_required for case in scoped.cases):
            raise ValueError(f"{split} needs JS-required static coverage gaps")
    assert_split_partition(corpus)


def assert_split_partition(corpus: CoverageCorpus) -> None:
    groups: dict[str, set[str]] = {"pilot": set(), "blind": set()}
    urls: dict[str, set[str]] = {"pilot": set(), "blind": set()}
    for case in corpus.cases:
        groups[case.split].add(case.case_id)
        urls[case.split].add(case.canonical_url)
    if groups["pilot"] & groups["blind"]:
        raise ValueError("pilot/blind case ids overlap")
    if urls["pilot"] & urls["blind"]:
        raise ValueError("pilot/blind canonical URLs overlap")


def classify_case(case: CoverageCase, registry: SourceRegistry) -> CaseOutcome:
    """Classify one gold source against catalog + static acquisition only."""
    family_known = _catalog_family_known(case.catalog_family)
    host_known = _host_registered(case.canonical_url, registry)
    discovered = family_known and (
        case.catalog_family in _FIRST_CLASS_FAMILIES
        or case.catalog_family == "hacker_news_discovery"
        or host_known
        or case.catalog_family in {"generic_web", "official_changelog", "documentation"}
    )
    if case.catalog_family not in {kind.value for kind in SourceKind}:
        discovered = False

    authoritative = _predict_authoritative(case)
    if case.js_required:
        return CaseOutcome(
            case.case_id,
            discovered,
            authoritative,
            acquired=False,
            update_detected=False,
            outcome="static_coverage_gap",
            reason="static HTTP cannot recover JS-rendered content; #64 not implemented",
        )
    if not discovered:
        return CaseOutcome(
            case.case_id,
            False,
            authoritative,
            acquired=False,
            update_detected=False,
            outcome="not_discovered",
            reason="source family is outside the current catalog/registry",
        )
    if not case.fetch_ok:
        return CaseOutcome(
            case.case_id,
            True,
            authoritative,
            acquired=False,
            update_detected=False,
            outcome="discovered_fetch_failed",
            reason="source was discovered but static acquisition failed",
        )
    update_detected = bool(
        case.update_expected and case.update_detectable_statically and case.fetch_ok
    )
    if case.update_expected and not update_detected:
        return CaseOutcome(
            case.case_id,
            True,
            authoritative,
            acquired=True,
            update_detected=False,
            outcome="fetched_change_missed",
            reason="static snapshot was fetched but the meaningful change was not detected",
        )
    return CaseOutcome(
        case.case_id,
        True,
        authoritative,
        acquired=True,
        update_detected=update_detected or not case.update_expected,
        outcome="covered",
        reason="catalogued family with static acquisition",
    )


def evaluate_source_coverage(
    corpus: CoverageCorpus,
    *,
    split: str | None = None,
    registry: SourceRegistry | None = None,
) -> SourceCoverageReport:
    scoped = corpus.for_split(split) if split is not None else corpus
    source_registry = registry or SourceRegistry()
    outcomes = tuple(classify_case(case, source_registry) for case in scoped.cases)
    by_id = {row.case_id: row for row in outcomes}
    expected_discovered = [case for case in scoped.cases if case.expected_discovered]
    discovered_hits = sum(1 for case in expected_discovered if by_id[case.case_id].discovered)
    predicted_auth = [case for case in scoped.cases if by_id[case.case_id].authoritative_predicted]
    auth_hits = sum(1 for case in predicted_auth if case.expected_authoritative)
    acquirable = [
        case
        for case in scoped.cases
        if by_id[case.case_id].discovered and not case.js_required
    ]
    acquired_hits = sum(1 for case in acquirable if by_id[case.case_id].acquired)
    update_needed = [case for case in scoped.cases if case.update_expected and by_id[case.case_id].acquired]
    update_hits = sum(1 for case in update_needed if by_id[case.case_id].update_detected)
    delays = [
        case.delay_seconds
        for case in scoped.cases
        if by_id[case.case_id].acquired
    ]
    gap = sum(1 for row in outcomes if row.outcome == "static_coverage_gap")
    duplicate_rate = _duplicate_rate(scoped.cases)
    counts: dict[str, int] = defaultdict(int)
    for row in outcomes:
        counts[row.outcome] += 1
    return SourceCoverageReport(
        dataset_version=scoped.dataset_version,
        benchmark_version=BENCHMARK_VERSION,
        split=split,
        case_count=len(scoped.cases),
        discovery_recall=_ratio(discovered_hits, len(expected_discovered)),
        authoritative_source_precision=_ratio(auth_hits, len(predicted_auth)),
        acquisition_success_rate=_ratio(acquired_hits, len(acquirable)),
        update_detection_recall=_ratio(update_hits, len(update_needed)),
        median_acquisition_delay_seconds=float(median(delays)) if delays else 0.0,
        duplicate_source_rate=duplicate_rate,
        static_coverage_gap_rate=_ratio(gap, len(scoped.cases)),
        outcome_counts=dict(sorted(counts.items())),
        by_source_family=_segments(scoped.cases, outcomes, key=lambda case: case.source_family),
        by_information_type=_segments(scoped.cases, outcomes, key=lambda case: case.information_type),
        by_topic=_segments(scoped.cases, outcomes, key=lambda case: case.topic),
        cases=outcomes,
        js_rendering_implemented=False,
    )


def coverage_release_violations(
    report: SourceCoverageReport,
    floors: Mapping[str, float] | None = None,
) -> tuple[str, ...]:
    """Minimum floors. Every possible Web source is not required."""
    required = {
        "discovery_recall": 0.70,
        "authoritative_source_precision": 0.70,
        "acquisition_success_rate": 0.70,
        "update_detection_recall": 0.60,
    }
    if floors:
        required.update(floors)
    violations: list[str] = []
    for name, floor in required.items():
        observed = float(getattr(report, name))
        if observed < floor:
            violations.append(f"{name} {observed:.3f} < {floor:.3f}")
    if report.js_rendering_implemented:
        violations.append("JS rendering must stay out of this benchmark")
    return tuple(violations)


def require_coverage_release_gate(
    report: SourceCoverageReport,
    floors: Mapping[str, float] | None = None,
) -> None:
    violations = coverage_release_violations(report, floors)
    if violations:
        raise AssertionError("source coverage release gate failed: " + "; ".join(violations))


def write_report(report: SourceCoverageReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("baseline report must be an object")
    return payload


def _load_split_cases(path: Path) -> tuple[CoverageCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} must be a JSON array")
    return tuple(_case_from_record(CoverageCaseRecord.model_validate(raw)) for raw in payload)


def _case_from_record(record: CoverageCaseRecord) -> CoverageCase:
    return CoverageCase(
        case_id=record.case_id,
        split=record.split,
        topic=record.topic,
        ecosystem=record.ecosystem,
        information_type=record.information_type,
        source_family=record.source_family,
        catalog_family=record.catalog_family,
        authority=record.authority,
        canonical_url=record.canonical_url,
        publisher=record.publisher,
        provenance=record.provenance,
        expected_discovered=record.expected_discovered,
        js_required=record.js_required,
        fetch_ok=record.fetch_ok,
        update_expected=record.update_expected,
        update_detectable_statically=record.update_detectable_statically,
        delay_seconds=record.delay_seconds,
        duplicate_group=record.duplicate_group,
        rationale=record.rationale,
    )


def _catalog_family_known(family: str) -> bool:
    try:
        return SourceKind(family) in MVP_SOURCE_POLICIES
    except ValueError:
        return False


def _host_registered(url: str, registry: SourceRegistry) -> bool:
    try:
        canonical = canonicalize_url(url)
    except ValueError:
        return False
    if registry.find_publisher(url=canonical) is not None:
        return True
    host = urlparse(canonical).hostname
    for endpoint in registry.list_endpoints():
        if urlparse(endpoint.canonical_url).hostname == host:
            return True
    return False


def _predict_authoritative(case: CoverageCase) -> bool:
    try:
        policy = get_source_policy(SourceKind(case.catalog_family))
    except ValueError:
        return False
    if policy.discovery_only:
        return False
    return policy.authoritative


def _duplicate_rate(cases: Sequence[CoverageCase]) -> float:
    groups: dict[str, int] = defaultdict(int)
    for case in cases:
        groups[case.duplicate_group] += 1
    extras = sum(count - 1 for count in groups.values() if count > 1)
    return extras / len(cases) if cases else 0.0


def _segments(
    cases: Sequence[CoverageCase],
    outcomes: Sequence[CaseOutcome],
    *,
    key,
) -> tuple[SegmentMetrics, ...]:
    by_id = {row.case_id: row for row in outcomes}
    buckets: dict[str, list[CoverageCase]] = defaultdict(list)
    for case in cases:
        buckets[key(case)].append(case)
    rows: list[SegmentMetrics] = []
    for name, group in sorted(buckets.items()):
        expected = [case for case in group if case.expected_discovered]
        discovered = sum(1 for case in expected if by_id[case.case_id].discovered)
        predicted_auth = [case for case in group if by_id[case.case_id].authoritative_predicted]
        auth_hits = sum(1 for case in predicted_auth if case.expected_authoritative)
        acquirable = [
            case for case in group if by_id[case.case_id].discovered and not case.js_required
        ]
        acquired = sum(1 for case in acquirable if by_id[case.case_id].acquired)
        update_needed = [
            case for case in group if case.update_expected and by_id[case.case_id].acquired
        ]
        updates = sum(1 for case in update_needed if by_id[case.case_id].update_detected)
        gaps = sum(1 for case in group if by_id[case.case_id].outcome == "static_coverage_gap")
        rows.append(
            SegmentMetrics(
                key=name,
                case_count=len(group),
                discovery_recall=_ratio(discovered, len(expected)),
                authoritative_precision=_ratio(auth_hits, len(predicted_auth)),
                acquisition_success_rate=_ratio(acquired, len(acquirable)),
                update_detection_recall=_ratio(updates, len(update_needed)),
                static_coverage_gap_rate=_ratio(gaps, len(group)),
            )
        )
    return tuple(rows)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator
