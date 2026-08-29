"""Real-world Core Value validation corpus contract (#117, Phase 0 / PR A).

Fixes IDs, schema, versioning, provenance and split rules only.
Does not score production rankers, change knownness, or claim capacity targets.
Blind labels stay under tests/gold/.../blind/ and are refused by the
production-scoring loader. Capacity (100 events / 50 profiles / 2,000
judgments) is reported, not enforced, until later corpus PRs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.label_contract import assert_not_blind_for_production_scoring
from app.services.source_registry import canonicalize_url

DATASET_VERSION = "real-world-validation-v0.1"
CONTRACT_VERSION = "real-world-validation-contract-v1"
LABEL_PROTOCOL_VERSION = "label-protocol-v1"
SOURCE_FAMILIES = (
    "github_release",
    "github_advisory",
    "osv",
    "statuspage",
    "rss_atom",
    "json_feed",
    "generic_web",
    "official_changelog",
    "documentation",
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
JUDGMENT_STRATA = (
    "clear_positive",
    "semantic_adjacent",
    "hard_negative",
    "lexical_trap",
    "unrelated",
    "already_known",
    "new_detail",
    "cross_source_duplicate",
    "correction_conflict",
)
REQUIRED_SOURCE_FIELDS = (
    "source_id",
    "canonical_url",
    "publisher",
    "source_family",
    "information_type",
    "language",
    "collected_at",
    "content_hash",
    "evidence_locator",
    "event_id",
    "split",
)
TARGET_EVENTS = 100
TARGET_PROFILES = 50
TARGET_JUDGMENTS = 2000
TARGET_SOURCE_FAMILIES = 6
SPLITS = ("pilot", "dev", "blind")
SplitName = Literal["pilot", "dev", "blind"]
SourceFamilyName = Literal[
    "github_release",
    "github_advisory",
    "osv",
    "statuspage",
    "rss_atom",
    "json_feed",
    "generic_web",
    "official_changelog",
    "documentation",
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
LanguageName = Literal["ja", "en", "mixed"]
CohortName = Literal["cold_start", "history_rich"]
StratumName = Literal[
    "clear_positive",
    "semantic_adjacent",
    "hard_negative",
    "lexical_trap",
    "unrelated",
    "already_known",
    "new_detail",
    "cross_source_duplicate",
    "correction_conflict",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRecord(_Strict):
    source_id: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    source_family: SourceFamilyName
    information_type: InformationTypeName
    language: LanguageName
    collected_at: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    evidence_locator: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    split: SplitName
    raw_evidence: str = ""
    normalized_evidence: str = ""
    static_fetch_ok: bool = True
    static_normalize_insufficient: bool = False
    js_render_would_recover: bool = False


class EventRecord(_Strict):
    event_id: str = Field(min_length=1)
    split: SplitName
    title: str = Field(min_length=1)
    information_type: InformationTypeName
    language: LanguageName
    redundancy_group: str = Field(min_length=1)
    mirror_group: str = Field(min_length=1)
    occurred_at: str = Field(min_length=1)
    provenance: str = Field(min_length=1)


class ProfileRecord(_Strict):
    profile_id: str = Field(min_length=1)
    split: SplitName
    constructed_profile: bool
    cohort: CohortName
    persona_template: str = Field(min_length=1)
    language_focus: LanguageName
    interest_breadth: Literal["broad", "narrow"]
    ecosystem: Literal["popular", "niche"]
    explicit_interests: list[str]
    followed_products: list[str]
    selected_repositories: list[str]
    security_sensitivity: Literal["low", "medium", "high"]
    known_before_event_ids: list[str] = Field(default_factory=list)
    prior_feedback: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_constructed_marker(self) -> ProfileRecord:
        if not self.constructed_profile:
            raise ValueError("Phase 0 profiles must set constructed_profile=true")
        return self


class JudgmentRecord(_Strict):
    judgment_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    split: SplitName
    stratum: StratumName
    relevance: int = Field(ge=0, le=3)
    importance_to_user: int = Field(ge=0, le=3)
    known_before: bool
    should_surface: bool
    rationale: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    label_protocol_version: str
    dataset_version: str
    ambiguous: bool = False


class SplitIndex(_Strict):
    split: SplitName
    source_ids: list[str]
    event_ids: list[str]
    profile_ids: list[str]
    judgment_ids: list[str]


class ValidationManifest(_Strict):
    dataset_id: str
    dataset_version: str
    contract_version: str
    label_protocol_version: str
    required_source_fields: list[str]
    targets: dict[str, int]
    splits: list[str]
    leakage_checks: list[str]
    files: dict[str, str]
    production_behavior_changed: bool
    phase: str
    note: str = ""


@dataclass(frozen=True)
class ValidationCorpus:
    manifest: ValidationManifest
    sources: tuple[SourceRecord, ...]
    events: tuple[EventRecord, ...]
    profiles: tuple[ProfileRecord, ...]
    judgments: tuple[JudgmentRecord, ...]
    indexes: dict[str, SplitIndex]

    def for_split(self, split: SplitName) -> ValidationCorpus:
        return ValidationCorpus(
            manifest=self.manifest,
            sources=tuple(row for row in self.sources if row.split == split),
            events=tuple(row for row in self.events if row.split == split),
            profiles=tuple(row for row in self.profiles if row.split == split),
            judgments=tuple(row for row in self.judgments if row.split == split),
            indexes={split: self.indexes[split]} if split in self.indexes else {},
        )

    def without_blind(self) -> ValidationCorpus:
        return ValidationCorpus(
            manifest=self.manifest,
            sources=tuple(row for row in self.sources if row.split != "blind"),
            events=tuple(row for row in self.events if row.split != "blind"),
            profiles=tuple(row for row in self.profiles if row.split != "blind"),
            judgments=tuple(row for row in self.judgments if row.split != "blind"),
            indexes={key: value for key, value in self.indexes.items() if key != "blind"},
        )


@dataclass(frozen=True)
class CapacityStatus:
    event_count: int
    profile_count: int
    judgment_count: int
    source_family_count: int
    meets_targets: bool
    missing: tuple[str, ...]


@dataclass(frozen=True)
class LeakageReport:
    ok: bool
    violations: tuple[str, ...]


def load_real_world_validation(
    corpus_dir: Path,
    *,
    splits: Sequence[SplitName] = SPLITS,
) -> ValidationCorpus:
    wanted = tuple(splits)
    if not wanted:
        raise ValueError("at least one split is required")
    if any(split not in SPLITS for split in wanted):
        raise ValueError(f"unknown split in {wanted}")
    manifest = ValidationManifest.model_validate(_load_json(corpus_dir / "manifest.json"))
    sources = tuple(
        SourceRecord.model_validate(row)
        for row in _load_json_array(corpus_dir / "sources.json")
        if row.get("split") in wanted
    )
    events = tuple(
        EventRecord.model_validate(row)
        for row in _load_json_array(corpus_dir / "events.json")
        if row.get("split") in wanted
    )
    profiles = tuple(
        ProfileRecord.model_validate(row)
        for row in _load_json_array(corpus_dir / "profiles.json")
        if row.get("split") in wanted
    )
    judgments = tuple(
        JudgmentRecord.model_validate(row)
        for row in _load_json_array(corpus_dir / "judgments" / "records.json")
        if row.get("split") in wanted
    )
    indexes = {
        split: SplitIndex.model_validate(_load_json(corpus_dir / split / "index.json")) for split in wanted
    }
    corpus = ValidationCorpus(manifest, sources, events, profiles, judgments, indexes)
    validate_contract(corpus)
    return corpus


def load_real_world_validation_for_production_scoring(corpus_dir: Path) -> ValidationCorpus:
    """Load pilot+dev only. Never opens the blind index directory."""
    if "blind" in Path(corpus_dir).parts:
        raise ValueError("split=blind corpus path must not be imported by production scoring")
    assert_not_blind_for_production_scoring(split="pilot")
    return load_real_world_validation(corpus_dir, splits=("pilot", "dev"))


def validate_contract(corpus: ValidationCorpus) -> None:
    _validate_manifest(corpus.manifest)
    _assert_unique("source_id", [row.source_id for row in corpus.sources])
    _assert_unique("event_id", [row.event_id for row in corpus.events])
    _assert_unique("profile_id", [row.profile_id for row in corpus.profiles])
    _assert_unique("judgment_id", [row.judgment_id for row in corpus.judgments])
    events = {row.event_id: row for row in corpus.events}
    profiles = {row.profile_id: row for row in corpus.profiles}
    for source in corpus.sources:
        if source.event_id not in events:
            raise ValueError(f"source {source.source_id} references unknown event {source.event_id}")
        if events[source.event_id].split != source.split:
            raise ValueError(f"source {source.source_id} crosses event split")
    for profile in corpus.profiles:
        if not profile.constructed_profile:
            raise ValueError(f"profile {profile.profile_id} is not marked constructed")
        for event_id in profile.known_before_event_ids:
            if event_id not in events:
                raise ValueError(f"profile {profile.profile_id} known_before unknown event")
            if events[event_id].split != profile.split:
                raise ValueError(f"profile {profile.profile_id} known_before crosses split")
    for judgment in corpus.judgments:
        if judgment.profile_id not in profiles:
            raise ValueError(f"judgment {judgment.judgment_id} references unknown profile")
        if judgment.event_id not in events:
            raise ValueError(f"judgment {judgment.judgment_id} references unknown event")
        if judgment.split != profiles[judgment.profile_id].split:
            raise ValueError(f"judgment {judgment.judgment_id} crosses profile split")
        if judgment.split != events[judgment.event_id].split:
            raise ValueError(f"judgment {judgment.judgment_id} crosses event split")
        if judgment.dataset_version != DATASET_VERSION:
            raise ValueError(f"judgment {judgment.judgment_id} has unexpected dataset_version")
        if judgment.label_protocol_version != LABEL_PROTOCOL_VERSION:
            raise ValueError(f"judgment {judgment.judgment_id} has unexpected protocol")
    _assert_indexes_match(corpus)
    report = split_leakage_report(corpus)
    if not report.ok:
        raise ValueError("split leakage: " + "; ".join(report.violations))


def split_leakage_report(corpus: ValidationCorpus) -> LeakageReport:
    buckets: dict[str, dict[str, set[str]]] = {split: defaultdict(set) for split in SPLITS}
    for source in corpus.sources:
        buckets[source.split]["canonical_url"].add(canonicalize_url(source.canonical_url))
        buckets[source.split]["event_id"].add(source.event_id)
    for event in corpus.events:
        buckets[event.split]["event_id"].add(event.event_id)
        buckets[event.split]["mirror_group"].add(event.mirror_group)
        buckets[event.split]["redundancy_group"].add(event.redundancy_group)
    for profile in corpus.profiles:
        buckets[profile.split]["profile_id"].add(profile.profile_id)
    violations: list[str] = []
    for left, right in (("pilot", "dev"), ("pilot", "blind"), ("dev", "blind")):
        for kind in ("canonical_url", "event_id", "mirror_group", "redundancy_group", "profile_id"):
            overlap = buckets[left][kind] & buckets[right][kind]
            if overlap:
                sample = ", ".join(sorted(overlap)[:4])
                violations.append(f"{left}/{right} {kind} leakage: {sample}")
    return LeakageReport(ok=not violations, violations=tuple(violations))


def capacity_status(corpus: ValidationCorpus) -> CapacityStatus:
    families = {row.source_family for row in corpus.sources}
    missing: list[str] = []
    if len(corpus.events) < TARGET_EVENTS:
        missing.append(f"events {len(corpus.events)} < {TARGET_EVENTS}")
    if len(corpus.profiles) < TARGET_PROFILES:
        missing.append(f"profiles {len(corpus.profiles)} < {TARGET_PROFILES}")
    if len(corpus.judgments) < TARGET_JUDGMENTS:
        missing.append(f"judgments {len(corpus.judgments)} < {TARGET_JUDGMENTS}")
    if len(families) < TARGET_SOURCE_FAMILIES:
        missing.append(f"source_families {len(families)} < {TARGET_SOURCE_FAMILIES}")
    return CapacityStatus(
        event_count=len(corpus.events),
        profile_count=len(corpus.profiles),
        judgment_count=len(corpus.judgments),
        source_family_count=len(families),
        meets_targets=not missing,
        missing=tuple(missing),
    )


def _validate_manifest(manifest: ValidationManifest) -> None:
    if manifest.dataset_version != DATASET_VERSION:
        raise ValueError("manifest dataset_version mismatch")
    if manifest.contract_version != CONTRACT_VERSION:
        raise ValueError("manifest contract_version mismatch")
    if manifest.label_protocol_version != LABEL_PROTOCOL_VERSION:
        raise ValueError("manifest label_protocol_version mismatch")
    if list(manifest.required_source_fields) != list(REQUIRED_SOURCE_FIELDS):
        raise ValueError("manifest required_source_fields drifted")
    if manifest.production_behavior_changed:
        raise ValueError("Phase 0 contract must not change production behavior")
    if set(manifest.splits) != set(SPLITS):
        raise ValueError("manifest splits must be pilot/dev/blind")


def _assert_indexes_match(corpus: ValidationCorpus) -> None:
    for split, index in corpus.indexes.items():
        if index.split != split:
            raise ValueError(f"{split} index split field mismatch")
        expected = {
            "source_ids": {row.source_id for row in corpus.sources if row.split == split},
            "event_ids": {row.event_id for row in corpus.events if row.split == split},
            "profile_ids": {row.profile_id for row in corpus.profiles if row.split == split},
            "judgment_ids": {row.judgment_id for row in corpus.judgments if row.split == split},
        }
        observed = {
            "source_ids": set(index.source_ids),
            "event_ids": set(index.event_ids),
            "profile_ids": set(index.profile_ids),
            "judgment_ids": set(index.judgment_ids),
        }
        for key, wanted in expected.items():
            if observed[key] != wanted:
                raise ValueError(f"{split} index {key} does not match records")


def _assert_unique(label: str, values: Sequence[str]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_array(path: Path) -> list[Any]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"{path} must be a JSON array")
    return payload


def iter_required_source_fields() -> Iterable[str]:
    return REQUIRED_SOURCE_FIELDS
