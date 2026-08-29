"""Real-world Core Value validation corpus contract (#117, integrity v1.1).

Fixes IDs, schema, versioning, provenance, physical split isolation, and
real-event rules. Does not score production rankers or change knownness.

Blind labels live only under tests/gold/.../blind/*.json. The production
scoring loader constructs pilot/dev paths only and never opens blind files.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.label_contract import assert_not_blind_for_production_scoring
from app.services.source_registry import canonicalize_url

DATASET_VERSION = "real-world-validation-v0.2"
CONTRACT_VERSION = "real-world-validation-contract-v1.1"
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
    "source_role",
    "fetch",
    "evidence_text",
    "normalized_evidence",
)
TARGET_EVENTS = 100
TARGET_PROFILES = 50
TARGET_JUDGMENTS = 2000
TARGET_SOURCE_FAMILIES = 6
SPLITS = ("pilot", "dev", "blind")
PRODUCTION_SCORING_SPLITS: tuple[Literal["pilot", "dev"], ...] = ("pilot", "dev")
SPLIT_RECORD_FILES = (
    "sources.json",
    "events.json",
    "profiles.json",
    "judgments.json",
    "index.json",
)
PLACEHOLDER_OCCURRED_AT = frozenset({"2024-08-01T00:00:00Z"})
ALLOWED_OCCURRED_AT_PROVENANCE = frozenset(
    {
        "github_release.published_at",
        "github_advisory.published_at",
        "github_git_commit.committer.date",
        "osv.published",
        "html_time_datetime",
        "html_visible_publish_date",
        "html_url_path_date",
    }
)
PERSONA_INDEPENDENCE_NOTE = (
    "Constructed profiles are clustered by persona_template. Do not treat "
    "len(profiles) as independent n for bootstrap CIs; cluster by persona family."
)

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
SourceRoleName = Literal["event_page", "discovery_endpoint", "contract_fixture"]
EventRecordKind = Literal["event_update", "contract_fixture"]
FetchKindName = Literal["live_https", "local_contract_fixture"]

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FetchMetadata(_Strict):
    fetch_kind: FetchKindName
    url: str = Field(min_length=1)
    requested_at: str = Field(min_length=1)
    http_status: int = Field(ge=0, le=599)
    content_type: str | None = None
    final_url: str = Field(min_length=1)
    etag: str | None = None
    last_modified: str | None = None
    artifact_relpath: str = Field(min_length=1)


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
    event_id: str | None = None
    split: SplitName
    source_role: SourceRoleName
    fetch: FetchMetadata
    evidence_text: str = Field(min_length=1)
    normalized_evidence: str = Field(min_length=1)
    static_fetch_ok: bool = True
    static_normalize_insufficient: bool = False
    js_render_would_recover: bool = False

    @model_validator(mode="after")
    def role_matches_event_link(self) -> SourceRecord:
        if self.source_role == "discovery_endpoint":
            if self.event_id:
                raise ValueError(f"source {self.source_id} discovery_endpoint must not claim an event_id")
            return self
        if not self.event_id:
            raise ValueError(f"source {self.source_id} role {self.source_role} requires event_id")
        return self


class EventRecord(_Strict):
    event_id: str = Field(min_length=1)
    split: SplitName
    title: str = Field(min_length=1)
    information_type: InformationTypeName
    language: LanguageName
    redundancy_group: str = Field(min_length=1)
    mirror_group: str = Field(min_length=1)
    record_kind: EventRecordKind
    is_real_event: bool
    published_at: str | None = None
    updated_at: str | None = None
    observed_at: str | None = None
    effective_at: str | None = None
    occurred_at: str | None = None
    occurred_at_provenance: str | None = None
    occurred_at_basis: str | None = None
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def real_event_and_time_rules(self) -> EventRecord:
        if self.record_kind == "contract_fixture" and self.is_real_event:
            raise ValueError(f"event {self.event_id} contract_fixture cannot be a real event")
        if self.record_kind == "event_update" and not self.is_real_event:
            raise ValueError(f"event {self.event_id} event_update must set is_real_event=true")
        if self.occurred_at in PLACEHOLDER_OCCURRED_AT:
            raise ValueError(f"event {self.event_id} uses forbidden placeholder occurred_at")
        if self.occurred_at and not self.occurred_at_provenance:
            raise ValueError(f"event {self.event_id} occurred_at lacks provenance")
        if self.occurred_at_provenance and self.occurred_at_provenance not in ALLOWED_OCCURRED_AT_PROVENANCE:
            raise ValueError(f"event {self.event_id} has unknown occurred_at_provenance")
        if self.occurred_at_provenance and not self.occurred_at:
            raise ValueError(f"event {self.event_id} provenance is set but occurred_at is null")
        if self.is_real_event and self.occurred_at and not self.occurred_at_basis:
            raise ValueError(f"event {self.event_id} occurred_at lacks basis excerpt")
        return self


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
    persona_independence_note: str = ""


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

    def real_events(self) -> tuple[EventRecord, ...]:
        return tuple(row for row in self.events if row.is_real_event)


@dataclass(frozen=True)
class CapacityStatus:
    event_count: int
    real_event_count: int
    profile_count: int
    judgment_count: int
    source_family_count: int
    persona_template_count: int
    meets_targets: bool
    missing: tuple[str, ...]


@dataclass(frozen=True)
class LeakageReport:
    ok: bool
    violations: tuple[str, ...]


def split_record_paths(corpus_dir: Path, split: SplitName) -> dict[str, Path]:
    """Build record paths for one split directory. Callers choose the split."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split}")
    base = Path(corpus_dir) / split
    return {name.removesuffix(".json"): base / name for name in SPLIT_RECORD_FILES}


def production_scoring_record_paths(corpus_dir: Path) -> tuple[Path, ...]:
    """Paths the production-scoring loader may construct. Never includes blind."""
    paths: list[Path] = [Path(corpus_dir) / "manifest.json"]
    for split in PRODUCTION_SCORING_SPLITS:
        if split == "blind":
            raise RuntimeError("production scoring splits must not include blind")
        paths.extend(split_record_paths(corpus_dir, split).values())
    return tuple(paths)


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
    root = Path(corpus_dir)
    manifest = ValidationManifest.model_validate(_load_json(root / "manifest.json"))
    sources: list[SourceRecord] = []
    events: list[EventRecord] = []
    profiles: list[ProfileRecord] = []
    judgments: list[JudgmentRecord] = []
    indexes: dict[str, SplitIndex] = {}
    for split in wanted:
        paths = split_record_paths(root, split)
        sources.extend(_load_validated_records(paths["sources"], SourceRecord, split))
        events.extend(_load_validated_records(paths["events"], EventRecord, split))
        profiles.extend(_load_validated_records(paths["profiles"], ProfileRecord, split))
        judgments.extend(_load_validated_records(paths["judgments"], JudgmentRecord, split))
        index = SplitIndex.model_validate(_load_json(paths["index"]))
        if index.split != split:
            raise ValueError(f"{paths['index']} split field does not match directory")
        indexes[split] = index
    corpus = ValidationCorpus(
        manifest,
        tuple(sources),
        tuple(events),
        tuple(profiles),
        tuple(judgments),
        indexes,
    )
    validate_contract(corpus, corpus_dir=root)
    return corpus


def load_real_world_validation_for_production_scoring(corpus_dir: Path) -> ValidationCorpus:
    """Load pilot+dev only. Never constructs or opens a blind label path."""
    root = Path(corpus_dir)
    if "blind" in root.parts:
        raise ValueError("split=blind corpus path must not be imported by production scoring")
    assert_not_blind_for_production_scoring(split="pilot")
    for path in production_scoring_record_paths(root):
        if "blind" in path.parts:
            raise ValueError(f"production scoring constructed a blind path: {path}")
    return load_real_world_validation(root, splits=PRODUCTION_SCORING_SPLITS)


def validate_contract(corpus: ValidationCorpus, *, corpus_dir: Path | None = None) -> None:
    _validate_manifest(corpus.manifest)
    _assert_unique("source_id", [row.source_id for row in corpus.sources])
    _assert_unique("event_id", [row.event_id for row in corpus.events])
    _assert_unique("profile_id", [row.profile_id for row in corpus.profiles])
    _assert_unique("judgment_id", [row.judgment_id for row in corpus.judgments])
    assert_provenance(corpus, corpus_dir=corpus_dir)
    events = {row.event_id: row for row in corpus.events}
    profiles = {row.profile_id: row for row in corpus.profiles}
    for source in corpus.sources:
        if source.source_role == "discovery_endpoint":
            continue
        if source.event_id not in events:
            raise ValueError(f"source {source.source_id} references unknown event {source.event_id}")
        if events[source.event_id].split != source.split:
            raise ValueError(f"source {source.source_id} crosses event split")
        event = events[source.event_id]
        if source.source_role == "event_page" and event.record_kind != "event_update":
            raise ValueError(f"source {source.source_id} event_page must point at event_update")
        if source.source_role == "contract_fixture" and event.record_kind != "contract_fixture":
            raise ValueError(f"source {source.source_id} contract_fixture must point at contract event")
    for event in corpus.events:
        if event.is_real_event and event.record_kind != "event_update":
            raise ValueError(f"event {event.event_id} real-event flag disagrees with record_kind")
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


def assert_provenance(corpus: ValidationCorpus, *, corpus_dir: Path | None = None) -> None:
    """Bind content_hash to the saved fetch artifact, not to a handwritten summary."""
    for source in corpus.sources:
        if not source.canonical_url.startswith(("https://", "http://")):
            raise ValueError(f"source {source.source_id} is missing a URL")
        if not source.collected_at:
            raise ValueError(f"source {source.source_id} is missing collected_at")
        if not source.evidence_locator:
            raise ValueError(f"source {source.source_id} is missing evidence_locator")
        if not source.evidence_text.strip():
            raise ValueError(f"source {source.source_id} is missing evidence_text")
        if not source.normalized_evidence.strip():
            raise ValueError(f"source {source.source_id} is missing normalized_evidence")
        if source.fetch.artifact_relpath != f"artifacts/{source.source_id}/body.bin":
            raise ValueError(f"source {source.source_id} artifact_relpath must be artifacts/<id>/body.bin")
        if source.fetch.fetch_kind == "live_https" and source.fetch.http_status != 200:
            raise ValueError(f"source {source.source_id} live fetch did not return HTTP 200")
        if source.fetch.fetch_kind == "local_contract_fixture" and source.source_role != "contract_fixture":
            raise ValueError(f"source {source.source_id} local fixture fetch_kind requires contract_fixture")
        if corpus_dir is not None:
            body = _read_artifact_bytes(Path(corpus_dir), source)
            digest = hashlib.sha256(body).hexdigest()
            if digest != source.content_hash:
                raise ValueError(f"source {source.source_id} content_hash does not match artifact bytes")
            text = body.decode("utf-8")
            if source.evidence_text not in text:
                raise ValueError(f"source {source.source_id} evidence_text is not in the saved artifact")
    for event in corpus.events:
        if not event.provenance.strip():
            raise ValueError(f"event {event.event_id} is missing provenance")


def coverage_inventory(corpus: ValidationCorpus) -> dict[str, int]:
    """Counts only. Minimum floors are enforced after collection PRs, not here."""
    real = corpus.real_events()
    event_pages = [row for row in corpus.sources if row.source_role == "event_page"]
    return {
        "events": len(corpus.events),
        "real_events": len(real),
        "contract_fixture_events": sum(1 for row in corpus.events if row.record_kind == "contract_fixture"),
        "discovery_sources": sum(1 for row in corpus.sources if row.source_role == "discovery_endpoint"),
        "profiles": len(corpus.profiles),
        "judgments": len(corpus.judgments),
        "source_families": len({row.source_family for row in event_pages}),
        "information_types": len({row.information_type for row in event_pages}),
        "languages": len({row.language for row in event_pages}),
        "persona_templates": len({row.persona_template for row in corpus.profiles}),
    }


def split_leakage_report(corpus: ValidationCorpus) -> LeakageReport:
    buckets: dict[str, dict[str, set[str]]] = {split: defaultdict(set) for split in SPLITS}
    for source in corpus.sources:
        buckets[source.split]["canonical_url"].add(canonicalize_url(source.canonical_url))
        if source.event_id:
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
    real = corpus.real_events()
    event_pages = [row for row in corpus.sources if row.source_role == "event_page"]
    families = {row.source_family for row in event_pages}
    persona_templates = {row.persona_template for row in corpus.profiles}
    missing: list[str] = []
    if len(real) < TARGET_EVENTS:
        missing.append(f"real_events {len(real)} < {TARGET_EVENTS}")
    if len(corpus.profiles) < TARGET_PROFILES:
        missing.append(f"profiles {len(corpus.profiles)} < {TARGET_PROFILES}")
    if len(corpus.judgments) < TARGET_JUDGMENTS:
        missing.append(f"judgments {len(corpus.judgments)} < {TARGET_JUDGMENTS}")
    if len(families) < TARGET_SOURCE_FAMILIES:
        missing.append(f"source_families {len(families)} < {TARGET_SOURCE_FAMILIES}")
    return CapacityStatus(
        event_count=len(corpus.events),
        real_event_count=len(real),
        profile_count=len(corpus.profiles),
        judgment_count=len(corpus.judgments),
        source_family_count=len(families),
        persona_template_count=len(persona_templates),
        meets_targets=not missing,
        missing=tuple(missing),
    )


def persona_template_counts(corpus: ValidationCorpus) -> dict[str, int]:
    return dict(Counter(row.persona_template for row in corpus.profiles))


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
    if manifest.persona_independence_note != PERSONA_INDEPENDENCE_NOTE:
        raise ValueError("manifest persona_independence_note drifted")


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


def _load_validated_records[T: BaseModel](
    path: Path,
    model: type[T],
    expected_split: SplitName,
) -> list[T]:
    rows = _load_json_array(path)
    validated: list[T] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}[{index}] must be an object")
        record = model.model_validate(row)
        split = record.model_dump()["split"]
        if split != expected_split:
            raise ValueError(f"{path}[{index}] split={split!r} does not match directory {expected_split}")
        validated.append(record)
    return validated


def _read_artifact_bytes(corpus_dir: Path, source: SourceRecord) -> bytes:
    artifact_root = (corpus_dir / "artifacts").resolve()
    path = (corpus_dir / source.fetch.artifact_relpath).resolve()
    if path != artifact_root / source.source_id / "body.bin":
        raise ValueError(f"source {source.source_id} artifact path escaped artifacts/")
    if not path.is_file():
        raise ValueError(f"source {source.source_id} artifact is missing: {path}")
    return path.read_bytes()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_array(path: Path) -> list[Any]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"{path} must be a JSON array")
    return payload


def iter_required_source_fields() -> Iterable[str]:
    return REQUIRED_SOURCE_FIELDS
