from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

IMPACT_SIGNAL_VERSION = "impact-signals-v1"
UNKNOWN = "unknown"

Confidence = Literal["high", "medium", "low"]

SIGNAL_NAMES: tuple[str, ...] = (
    "correction_or_conflict",
    "security_severity",
    "security_exploitability",
    "affected_packages",
    "breaking_deprecation_removal",
    "migration_required",
    "incident_impact",
    "incident_status",
    "incident_recovery",
    "version_significance",
    "deadline",
    "scope_audience",
)

# Ranking / novelty inputs must never influence factual impact features.
_IGNORED_RECORD_KEYS = frozenset(
    {
        "relation_level",
        "novelty",
        "relation",
        "personalization_rank",
        "matched_topics",
        "matched_repos",
        "matched_repos_json",
    }
)

_SEVERITY_ALIASES = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "moderate": "medium",
    "low": "low",
}

_CORRECTION_DELTA_TYPES = frozenset({"correction"})
_CONFLICT_DELTA_TYPES = frozenset({"unresolved_contradiction", "unresolved_conflict"})

_INCIDENT_IMPACTS = frozenset({"critical", "major", "minor", "none"})
_RECOVERED_STATUSES = frozenset({"resolved", "postmortem"})
_RECOVERING_STATUSES = frozenset({"monitoring"})
_UNRESOLVED_STATUSES = frozenset({"investigating", "identified"})

_DEPRECATION_LIFECYCLE = frozenset({"deprecation_announced", "deprecated"})
_REMOVAL_LIFECYCLE = frozenset({"retirement_announced", "retired"})

_PROSE_FIELDS = ("title", "name", "summary", "body", "description", "detail", "content", "incident_name")

_CORRECTION_PATTERNS = (
    re.compile(r"\bcorrection\s*:", re.IGNORECASE),
    re.compile(r"\bprevious update (?:was|is) incorrect\b", re.IGNORECASE),
    re.compile(
        r"\bwe previously (?:stated|reported).{0,80}\b(?:incorrect|wrong)\b",
        re.IGNORECASE,
    ),
)

_BREAKING_PATTERNS = (
    re.compile(r"\bbreaking[- ]changes?\b", re.IGNORECASE),
    re.compile(r"(?m)^#{1,3}\s*breaking\b", re.IGNORECASE),
    re.compile(r"\*\*breaking\*\*", re.IGNORECASE),
)

_DEPRECATION_PATTERNS = (
    re.compile(r"^upcoming deprecation of\b", re.IGNORECASE),
    re.compile(r"\bupcoming deprecation of\b", re.IGNORECASE),
    re.compile(r"\b(?:is|are) now deprecated\b", re.IGNORECASE),
    re.compile(r"\b(?:is|are) deprecated\b", re.IGNORECASE),
)

_REMOVAL_PATTERNS = (
    re.compile(r"\b(?:is being fully retired|will be retired|is now retired)\b", re.IGNORECASE),
    re.compile(r"\bthis (?:release|version) removes\b", re.IGNORECASE),
    re.compile(r"(?m)^#{1,3}\s*removed\b", re.IGNORECASE),
)

_MIGRATION_PATTERNS = (
    re.compile(r"\bmigration required\b", re.IGNORECASE),
    re.compile(r"\byou must migrate\b", re.IGNORECASE),
    re.compile(r"\bmigration (?:guide|path|notes)\b", re.IGNORECASE),
)

_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)"
    r"(?:\.(?P<minor>0|[1-9]\d*))?"
    r"(?:\.(?P<patch>0|[1-9]\d*))?"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)

_CVSS_METRIC_RE = re.compile(r"(?:^|/)(?P<key>AV|AC|PR|UI):(?P<value>[A-Z])")
_ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_DEADLINE_HINT_RE = re.compile(
    r"\b(?:effective(?: date)?|deadline|until|sunset|due(?: date)?|retir\w+|deprecat\w+)\b",
    re.IGNORECASE,
)
_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_OSV_SOURCE_KEY_RE = re.compile(
    r"^(?P<ecosystem>[^:]+):(?P<name>[^@]+)@(?P<version>.+)$"
)
_CVSS_VECTOR_RE = re.compile(r"CVSS:\d+(?:\.\d+)?/.+")


@dataclass(frozen=True)
class ImpactSignal:
    value: Any
    source_field: str
    reason: str
    confidence: Confidence


@dataclass(frozen=True)
class ImpactSignals:
    version: str
    correction_or_conflict: ImpactSignal
    security_severity: ImpactSignal
    security_exploitability: ImpactSignal
    affected_packages: ImpactSignal
    breaking_deprecation_removal: ImpactSignal
    migration_required: ImpactSignal
    incident_impact: ImpactSignal
    incident_status: ImpactSignal
    incident_recovery: ImpactSignal
    version_significance: ImpactSignal
    deadline: ImpactSignal
    scope_audience: ImpactSignal

    def to_snapshot(self) -> dict[str, Any]:
        """JSON-serializable snapshot ranking can consume without reparsing source text."""
        signals = {
            name: {
                "value": _jsonable(getattr(self, name).value),
                "source_field": getattr(self, name).source_field,
                "reason": getattr(self, name).reason,
                "confidence": getattr(self, name).confidence,
            }
            for name in SIGNAL_NAMES
        }
        return {"version": self.version, "signals": signals}

    def to_json(self) -> str:
        return json.dumps(self.to_snapshot(), sort_keys=True, separators=(",", ":"))


def extract_impact_signals(record: Mapping[str, Any]) -> ImpactSignals:
    """Extract versioned impact/urgency signals from a structured source record.

    ``relation_level`` and ``novelty`` are not accepted as parameters and are ignored
    if present on the record. Missing evidence stays ``unknown`` rather than defaulting
    high. Prose regex is used only as a low-confidence fallback and is labeled inferred.
    """
    view = _RecordView(record)
    affected = _extract_affected_packages(view)
    return ImpactSignals(
        version=IMPACT_SIGNAL_VERSION,
        correction_or_conflict=_extract_correction_or_conflict(view),
        security_severity=_extract_security_severity(view),
        security_exploitability=_extract_security_exploitability(view),
        affected_packages=affected,
        breaking_deprecation_removal=_extract_breaking_deprecation_removal(view),
        migration_required=_extract_migration_required(view),
        incident_impact=_extract_incident_impact(view),
        incident_status=_extract_incident_status(view),
        incident_recovery=_extract_incident_recovery(view),
        version_significance=_extract_version_significance(view),
        deadline=_extract_deadline(view),
        scope_audience=_extract_scope_audience(view, affected),
    )


def features_for_ranking(signals: ImpactSignals) -> dict[str, Any]:
    """Stable feature snapshot for later ranking consumption."""
    return signals.to_snapshot()


def snapshot_impact_signals(record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract once and return a frozen JSON-serializable snapshot."""
    return extract_impact_signals(record).to_snapshot()


class _RecordView:
    def __init__(self, record: Mapping[str, Any]) -> None:
        self.record = record
        payload = record.get("payload")
        self.payload = payload if isinstance(payload, dict) else {}

    def get(self, *names: str) -> tuple[str, Any] | None:
        for name in names:
            if name in _IGNORED_RECORD_KEYS:
                continue
            if name in self.record and _has_evidence(self.record[name]):
                return name, self.record[name]
            if name in self.payload and _has_evidence(self.payload[name]):
                return f"payload.{name}", self.payload[name]
        return None

    def get_raw(self, *names: str) -> tuple[str, Any] | None:
        """Like get(), but treats explicit False / 0 as present evidence."""
        for name in names:
            if name in _IGNORED_RECORD_KEYS:
                continue
            if name in self.record and self.record[name] is not None:
                value = self.record[name]
                if isinstance(value, str) and not value.strip():
                    continue
                return name, value
            if name in self.payload and self.payload[name] is not None:
                value = self.payload[name]
                if isinstance(value, str) and not value.strip():
                    continue
                return f"payload.{name}", value
        return None

    def prose_fields(self) -> tuple[tuple[str, str], ...]:
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for name in _PROSE_FIELDS:
            hit = self.get(name)
            if hit is None:
                continue
            field, value = hit
            if not isinstance(value, str):
                continue
            text = " ".join(value.split())
            if text and text not in seen:
                seen.add(text)
                found.append((field, text))
        return tuple(found)


def _extract_correction_or_conflict(view: _RecordView) -> ImpactSignal:
    conflict = view.get("unresolved_source_conflict")
    if conflict is not None and conflict[1] is True:
        return ImpactSignal(
            value="conflict",
            source_field=conflict[0],
            reason="Structured unresolved_source_conflict flag is true.",
            confidence="high",
        )
    delta = view.get("delta_type", "revision_type", "revision_hint")
    if delta is not None and isinstance(delta[1], str):
        normalized = delta[1].strip().casefold()
        if normalized in _CONFLICT_DELTA_TYPES:
            return ImpactSignal(
                value="conflict",
                source_field=delta[0],
                reason=f"Structured {delta[0]} marks an unresolved conflict.",
                confidence="high",
            )
        if normalized in _CORRECTION_DELTA_TYPES:
            return ImpactSignal(
                value="correction",
                source_field=delta[0],
                reason=f"Structured {delta[0]} marks a correction.",
                confidence="high",
            )
    explicit = view.get("explicit_correction")
    if explicit is not None and explicit[1] is True:
        return ImpactSignal(
            value="correction",
            source_field=explicit[0],
            reason="Structured explicit_correction flag is true.",
            confidence="high",
        )
    for field, text in view.prose_fields():
        if any(pattern.search(text) for pattern in _CORRECTION_PATTERNS):
            return _inferred(
                field,
                "correction",
                "high-precision correction marker in source prose",
            )
    return _unknown()


def _extract_security_severity(view: _RecordView) -> ImpactSignal:
    qualitative = view.get("severity")
    if qualitative is not None and isinstance(qualitative[1], str):
        mapped = _SEVERITY_ALIASES.get(qualitative[1].strip().casefold())
        if mapped is not None:
            return ImpactSignal(
                value=mapped,
                source_field=qualitative[0],
                reason="Structured advisory severity field.",
                confidence="high",
            )
        return _unknown("Severity is present but not a known qualitative label.")
    for field_name in ("database_specific", "payload.database_specific"):
        container = view.payload if field_name.startswith("payload.") else view.record
        blob = container.get("database_specific")
        if not isinstance(blob, dict):
            continue
        raw = blob.get("severity")
        if not isinstance(raw, str) or not raw.strip():
            continue
        mapped = _SEVERITY_ALIASES.get(raw.strip().casefold())
        if mapped is None:
            continue
        source_field = (
            "payload.database_specific.severity"
            if field_name.startswith("payload.")
            else "database_specific.severity"
        )
        return ImpactSignal(
            value=mapped,
            source_field=source_field,
            reason="Structured database_specific.severity field.",
            confidence="high",
        )
    cvss_score = _cvss_numeric_score(view)
    if cvss_score is not None:
        field, score = cvss_score
        mapped = _severity_from_cvss_score(score)
        if mapped is not None:
            return ImpactSignal(
                value=mapped,
                source_field=field,
                reason=f"Mapped from structured CVSS score {score}.",
                confidence="high",
            )
    return _unknown()


def _extract_security_exploitability(view: _RecordView) -> ImpactSignal:
    explicit = view.get("exploitability", "exploitability_score")
    if explicit is not None:
        if isinstance(explicit[1], str):
            mapped = _SEVERITY_ALIASES.get(explicit[1].strip().casefold())
            if mapped is not None:
                return ImpactSignal(
                    value=mapped,
                    source_field=explicit[0],
                    reason="Structured exploitability field.",
                    confidence="high",
                )
        if isinstance(explicit[1], int | float):
            mapped = _exploitability_from_score(float(explicit[1]))
            return ImpactSignal(
                value=mapped,
                source_field=explicit[0],
                reason=f"Mapped from structured exploitability score {explicit[1]}.",
                confidence="high",
            )
    vector = _cvss_vector(view)
    if vector is not None:
        field, vector_string = vector
        metrics = {
            match.group("key"): match.group("value") for match in _CVSS_METRIC_RE.finditer(vector_string)
        }
        classified = _exploitability_from_metrics(metrics)
        if classified is not None:
            return ImpactSignal(
                value=classified,
                source_field=field,
                reason="Derived from structured CVSS exploitability metrics (AV/AC/PR/UI).",
                confidence="high",
            )
    return _unknown()


def _extract_affected_packages(view: _RecordView) -> ImpactSignal:
    packages: list[dict[str, str]] = []
    repositories: list[dict[str, str]] = []
    source_fields: list[str] = []

    def add_package(field: str, ecosystem: str, name: str) -> None:
        identifier = {"ecosystem": ecosystem, "name": name}
        if identifier not in packages:
            packages.append(identifier)
            if field not in source_fields:
                source_fields.append(field)

    def add_repo(field: str, full_name: str) -> None:
        identifier = {"full_name": full_name}
        if identifier not in repositories:
            repositories.append(identifier)
            if field not in source_fields:
                source_fields.append(field)

    for field_name in ("vulnerabilities", "affected"):
        hit = view.get(field_name)
        if hit is None or not isinstance(hit[1], list):
            continue
        for entry in hit[1]:
            if not isinstance(entry, dict):
                continue
            package = entry.get("package")
            if not isinstance(package, dict):
                continue
            name = package.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            ecosystem = package.get("ecosystem")
            eco_text = ecosystem.strip() if isinstance(ecosystem, str) else ""
            add_package(f"{hit[0]}[].package", eco_text, name.strip())

    package_hit = view.get("package")
    if package_hit is not None and isinstance(package_hit[1], dict):
        name = package_hit[1].get("name")
        if isinstance(name, str) and name.strip():
            ecosystem = package_hit[1].get("ecosystem")
            eco_text = ecosystem.strip() if isinstance(ecosystem, str) else ""
            add_package(package_hit[0], eco_text, name.strip())
    elif package_hit is not None and isinstance(package_hit[1], str) and package_hit[1].strip():
        add_package(package_hit[0], "", package_hit[1].strip())

    name_hit = view.get("package_name", "selected_package")
    if name_hit is not None and isinstance(name_hit[1], str):
        ecosystem_hit = view.get("ecosystem")
        eco_text = (
            ecosystem_hit[1].strip()
            if ecosystem_hit is not None and isinstance(ecosystem_hit[1], str)
            else ""
        )
        add_package(name_hit[0], eco_text, name_hit[1].strip())

    for repo_key in ("selected_repository", "repository_full_name", "full_name", "repository"):
        repo_hit = view.get(repo_key)
        if repo_hit is None:
            continue
        if isinstance(repo_hit[1], str) and _OWNER_REPO_RE.match(repo_hit[1].strip()):
            add_repo(repo_hit[0], repo_hit[1].strip())
        elif isinstance(repo_hit[1], dict):
            full_name = repo_hit[1].get("full_name")
            if isinstance(full_name, str) and _OWNER_REPO_RE.match(full_name.strip()):
                add_repo(repo_hit[0], full_name.strip())

    source_key = view.get("source_key")
    source_type = view.get("source_type")
    source_type_value = source_type[1] if source_type is not None else ""
    if source_key is not None and isinstance(source_key[1], str):
        key = source_key[1].strip()
        if source_type_value == "github_release" and _OWNER_REPO_RE.match(key):
            add_repo(source_key[0], key)
        elif source_type_value == "osv":
            match = _OSV_SOURCE_KEY_RE.match(key)
            if match is not None:
                add_package(source_key[0], match.group("ecosystem"), match.group("name"))

    if not packages and not repositories:
        return _unknown()

    packages.sort(key=lambda item: (item.get("ecosystem", ""), item.get("name", "")))
    repositories.sort(key=lambda item: item.get("full_name", ""))
    return ImpactSignal(
        value={"packages": packages, "repositories": repositories},
        source_field=",".join(source_fields),
        reason="Structured package or repository identifiers are present.",
        confidence="high",
    )


def _extract_breaking_deprecation_removal(view: _RecordView) -> ImpactSignal:
    detected: dict[str, str] = {}

    def mark(kind: str, field: str) -> None:
        detected.setdefault(kind, field)

    for flag_name in ("breaking", "breaking_change", "is_breaking"):
        hit = view.get(flag_name)
        if hit is not None and hit[1] is True:
            mark("breaking", hit[0])
    for flag_name in ("deprecated", "deprecation", "is_deprecated"):
        hit = view.get(flag_name)
        if hit is not None and hit[1] is True:
            mark("deprecation", hit[0])
    for flag_name in ("removed", "removal", "is_removed"):
        hit = view.get(flag_name)
        if hit is not None and hit[1] is True:
            mark("removal", hit[0])

    lifecycle = view.get("lifecycle_state", "state")
    if lifecycle is not None and isinstance(lifecycle[1], str):
        state = lifecycle[1].strip().casefold()
        if state in _DEPRECATION_LIFECYCLE:
            mark("deprecation", lifecycle[0])
        elif state in _REMOVAL_LIFECYCLE:
            mark("removal", lifecycle[0])

    inferred_reasons: list[str] = []
    if not detected:
        for field, text in view.prose_fields():
            if "breaking" not in detected and any(pattern.search(text) for pattern in _BREAKING_PATTERNS):
                mark("breaking", f"inferred:{field}")
                inferred_reasons.append(f"breaking marker in {field}")
            if "deprecation" not in detected and any(
                pattern.search(text) for pattern in _DEPRECATION_PATTERNS
            ):
                mark("deprecation", f"inferred:{field}")
                inferred_reasons.append(f"deprecation marker in {field}")
            if "removal" not in detected and any(pattern.search(text) for pattern in _REMOVAL_PATTERNS):
                mark("removal", f"inferred:{field}")
                inferred_reasons.append(f"removal/retirement marker in {field}")

    if not detected:
        return _unknown()

    kinds = tuple(kind for kind in ("breaking", "removal", "deprecation") if kind in detected)
    strongest = kinds[0]
    source_field = detected[strongest]
    inferred = source_field.startswith("inferred:")
    if inferred:
        return ImpactSignal(
            value=strongest,
            source_field=source_field,
            reason="Inferred from high-precision marker: " + "; ".join(inferred_reasons) + ".",
            confidence="low",
        )
    return ImpactSignal(
        value=strongest,
        source_field=source_field,
        reason=f"Structured flag or lifecycle state indicates {', '.join(kinds)}.",
        confidence="high",
    )


def _extract_migration_required(view: _RecordView) -> ImpactSignal:
    hit = view.get("migration_required", "requires_migration")
    if hit is not None and hit[1] is True:
        return ImpactSignal(
            value="yes",
            source_field=hit[0],
            reason="Structured migration_required flag is true.",
            confidence="high",
        )
    migration = view.get("migration")
    if migration is not None and isinstance(migration[1], str) and migration[1].strip():
        return ImpactSignal(
            value="yes",
            source_field=migration[0],
            reason="Structured migration field is present.",
            confidence="high",
        )
    for field, text in view.prose_fields():
        if any(pattern.search(text) for pattern in _MIGRATION_PATTERNS):
            return _inferred(field, "yes", "high-precision migration marker in source prose")
    return _unknown()


def _extract_incident_impact(view: _RecordView) -> ImpactSignal:
    hit = view.get("impact", "incident_impact")
    if hit is None or not isinstance(hit[1], str):
        return _unknown()
    normalized = hit[1].strip().casefold()
    if normalized not in _INCIDENT_IMPACTS:
        return _unknown("Impact is present but not a known Statuspage impact value.")
    return ImpactSignal(
        value=normalized,
        source_field=hit[0],
        reason="Structured incident impact field.",
        confidence="high",
    )


def _extract_incident_status(view: _RecordView) -> ImpactSignal:
    hit = view.get("status", "incident_status")
    if hit is None or not isinstance(hit[1], str) or not hit[1].strip():
        return _unknown()
    # Release "released"/"draft" and advisory "active" are not incident statuses.
    source_type = view.get("source_type")
    source_type_value = source_type[1] if source_type is not None else ""
    normalized = hit[1].strip().casefold()
    incident_statuses = _RECOVERED_STATUSES | _RECOVERING_STATUSES | _UNRESOLVED_STATUSES
    if source_type_value not in {"statuspage", "incident"} and normalized not in incident_statuses:
        return _unknown()
    if source_type_value in {"statuspage", "incident"} or normalized in incident_statuses:
        return ImpactSignal(
            value=normalized,
            source_field=hit[0],
            reason="Structured incident status field.",
            confidence="high",
        )
    return _unknown()


def _extract_incident_recovery(view: _RecordView) -> ImpactSignal:
    resolved = view.get("resolved")
    if resolved is not None and resolved[1] is True:
        return ImpactSignal(
            value="recovered",
            source_field=resolved[0],
            reason="Structured resolved flag is true.",
            confidence="high",
        )
    status = _extract_incident_status(view)
    if status.value == UNKNOWN:
        return _unknown()
    status_value = str(status.value)
    if status_value in _RECOVERED_STATUSES:
        recovery = "recovered"
    elif status_value in _RECOVERING_STATUSES:
        recovery = "recovering"
    elif status_value in _UNRESOLVED_STATUSES:
        recovery = "unresolved"
    else:
        return _unknown()
    return ImpactSignal(
        value=recovery,
        source_field=status.source_field,
        reason=f"Derived from structured incident status {status_value!r}.",
        confidence="high",
    )


def _extract_version_significance(view: _RecordView) -> ImpactSignal:
    prerelease = view.get_raw("prerelease")
    if prerelease is not None and prerelease[1] is True:
        return ImpactSignal(
            value="prerelease",
            source_field=prerelease[0],
            reason="Structured prerelease flag is true.",
            confidence="high",
        )
    for key in ("tag_name", "version"):
        hit = view.get(key)
        if hit is None or not isinstance(hit[1], str):
            continue
        classified = _classify_semver(hit[1].strip())
        if classified is None:
            continue
        return ImpactSignal(
            value=classified,
            source_field=hit[0],
            reason=f"Derived from structured {hit[0]} {hit[1]!r}.",
            confidence="high",
        )
    return _unknown()


def _extract_deadline(view: _RecordView) -> ImpactSignal:
    for key in (
        "deadline",
        "effective_date",
        "effective_at",
        "sunset_at",
        "retirement_date",
        "deprecated_at",
        "due_date",
    ):
        hit = view.get(key)
        if hit is None:
            continue
        if isinstance(hit[1], str) and hit[1].strip():
            return ImpactSignal(
                value=hit[1].strip(),
                source_field=hit[0],
                reason=f"Structured {hit[0]} field.",
                confidence="high",
            )
    for field, text in view.prose_fields():
        if _DEADLINE_HINT_RE.search(text) is None:
            continue
        match = _ISO_DATE_RE.search(text)
        if match is None:
            continue
        return _inferred(field, match.group(1), f"date {match.group(1)} near a deadline/effective cue")
    return _unknown()


def _extract_scope_audience(view: _RecordView, affected: ImpactSignal) -> ImpactSignal:
    hit = view.get("audience", "audience_breadth", "scope", "scope_breadth")
    if hit is not None and isinstance(hit[1], str) and hit[1].strip():
        return ImpactSignal(
            value=hit[1].strip(),
            source_field=hit[0],
            reason=f"Structured {hit[0]} field.",
            confidence="high",
        )
    if affected.value == UNKNOWN or not isinstance(affected.value, dict):
        return _unknown()
    packages = affected.value.get("packages")
    repositories = affected.value.get("repositories")
    package_count = len(packages) if isinstance(packages, list) else 0
    repo_count = len(repositories) if isinstance(repositories, list) else 0
    if package_count > 1:
        value = "multi_package"
    elif package_count == 1:
        value = "single_package"
    elif repo_count > 1:
        value = "multi_repository"
    elif repo_count == 1:
        value = "single_repository"
    else:
        return _unknown()
    return ImpactSignal(
        value=value,
        source_field=affected.source_field,
        reason="Derived from the count of structured package or repository identifiers.",
        confidence="high",
    )


def _unknown(reason: str = "No structured evidence for this signal.") -> ImpactSignal:
    return ImpactSignal(value=UNKNOWN, source_field="", reason=reason, confidence="low")


def _inferred(field: str, value: Any, reason: str) -> ImpactSignal:
    label = field if field.startswith("inferred:") else f"inferred:{field}"
    return ImpactSignal(
        value=value,
        source_field=label,
        reason=f"Inferred from prose: {reason}.",
        confidence="low",
    )


def _has_evidence(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool | int | float):
        return bool(value) if not isinstance(value, bool) else value
    if isinstance(value, list | tuple | dict):
        return True
    return True


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _classify_semver(tag: str) -> str | None:
    match = _SEMVER_RE.fullmatch(tag)
    if match is None:
        return None
    if match.group("pre"):
        return "prerelease"
    major = int(match.group("major"))
    minor = int(match.group("minor") or "0")
    patch_raw = match.group("patch")
    if patch_raw is None and match.group("minor") is None:
        return None
    patch = int(patch_raw or "0")
    if major >= 1 and minor == 0 and patch == 0:
        return "major"
    if patch != 0:
        return "patch"
    if minor != 0:
        return "minor"
    return None


def _cvss_numeric_score(view: _RecordView) -> tuple[str, float] | None:
    score_hit = view.get("cvss_score")
    if score_hit is not None and isinstance(score_hit[1], int | float):
        return score_hit[0], float(score_hit[1])
    cvss = view.get("cvss")
    if cvss is not None:
        if isinstance(cvss[1], int | float):
            return cvss[0], float(cvss[1])
        if isinstance(cvss[1], dict) and isinstance(cvss[1].get("score"), int | float):
            return f"{cvss[0]}.score", float(cvss[1]["score"])
    severity = view.get("severity")
    if severity is not None and isinstance(severity[1], list):
        for index, entry in enumerate(severity[1]):
            if not isinstance(entry, dict):
                continue
            score = entry.get("score")
            if isinstance(score, int | float):
                return f"{severity[0]}[{index}].score", float(score)
    return None


def _cvss_vector(view: _RecordView) -> tuple[str, str] | None:
    vector_hit = view.get("cvss_vector", "vector_string")
    if vector_hit is not None and isinstance(vector_hit[1], str) and _CVSS_VECTOR_RE.match(vector_hit[1]):
        return vector_hit[0], vector_hit[1]
    cvss = view.get("cvss")
    if cvss is not None and isinstance(cvss[1], dict):
        vector = cvss[1].get("vector_string")
        if isinstance(vector, str) and _CVSS_VECTOR_RE.match(vector):
            return f"{cvss[0]}.vector_string", vector
    severity = view.get("severity")
    if severity is not None and isinstance(severity[1], list):
        for index, entry in enumerate(severity[1]):
            if not isinstance(entry, dict):
                continue
            score = entry.get("score")
            if isinstance(score, str) and _CVSS_VECTOR_RE.match(score):
                return f"{severity[0]}[{index}].score", score
    return None


def _severity_from_cvss_score(score: float) -> str | None:
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score > 0.0:
        return "low"
    return None


def _exploitability_from_score(score: float) -> str:
    if score >= 3.0:
        return "high"
    if score >= 1.5:
        return "medium"
    return "low"


def _exploitability_from_metrics(metrics: Mapping[str, str]) -> str | None:
    attack_vector = metrics.get("AV")
    attack_complexity = metrics.get("AC")
    privileges = metrics.get("PR")
    user_interaction = metrics.get("UI")
    if not any((attack_vector, attack_complexity, privileges, user_interaction)):
        return None
    if (
        attack_vector == "N"
        and attack_complexity == "L"
        and privileges == "N"
        and user_interaction == "N"
    ):
        return "high"
    if attack_vector == "P" or (attack_complexity == "H" and privileges == "H"):
        return "low"
    return "medium"
