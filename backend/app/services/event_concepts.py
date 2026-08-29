from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from app.db.topic_catalog import TOPIC_ALIASES, TOPIC_CATALOG
from app.services.sbom_packages import parse_purl

EVENT_CONCEPT_VERSION = "event-concepts-v01"

ConceptType = Literal[
    "product_service",
    "language_runtime",
    "framework_library_package",
    "company_project",
    "repository",
    "vulnerability_advisory",
    "api_protocol",
    "feature_capability",
]
Confidence = Literal["high", "medium", "low"]
ConceptSource = Literal["structured", "prose"]

_LANGUAGE_RUNTIME = frozenset(
    {
        "Kotlin",
        "Java",
        "Python",
        "JavaScript",
        "TypeScript",
        "Go",
        "Rust",
        "Swift",
        "Dart",
        "Ruby",
        "PHP",
        "C#",
        "C++",
        "Node.js",
        "Bun",
        "Deno",
    }
)
_API_PROTOCOL = frozenset({"GraphQL", "gRPC", "OpenAPI", "Apollo GraphQL"})
_PRODUCT_SERVICE = frozenset(
    {
        "AWS",
        "Google Cloud",
        "Microsoft Azure",
        "Cloudflare",
        "Cloudflare Workers",
        "Vercel",
        "Netlify",
        "Firebase",
        "Supabase",
        "GitHub",
        "GitHub Actions",
        "GitLab",
        "CircleCI",
        "OpenAI API",
        "Anthropic API",
        "Gemini API",
        "Hugging Face",
        "Grafana",
        "Sentry",
        "Datadog",
        "Renovate",
        "Dependabot",
        "Stripe",
        "Twilio",
        "SendGrid",
        "Auth0",
        "Clerk",
    }
)
_COMPANY_PROJECT = frozenset(
    {"Google", "Microsoft", "Apple", "Amazon", "Meta", "OpenAI", "Cloudflare", "JetBrains"}
)
_AMBIGUOUS_CONCEPTS = frozenset({"java", "go", "swift", "rust", "react", "express", "rails"})
_PROSE_SKIP_ALIASES = frozenset({"js", "ts", "node", "next", "workers"})
_STRUCTURED_REPO_TYPES = frozenset({"github_release", "github_sbom"})
_STRUCTURED_ADVISORY_TYPES = frozenset({"github_advisory", "osv"})

_REPO_PRODUCTS: dict[str, str | None] = {
    "facebook/react": "react",
    "meta/react": "react",
    "vercel/next.js": "next-js",
    "vuejs/core": "vue",
    "vuejs/vue": "vue",
    "angular/angular": "angular",
    "sveltejs/svelte": "svelte",
    "spring-projects/spring-boot": "spring-boot",
    "rails/rails": "ruby-on-rails",
    "apple/swift": "swift",
    "golang/go": "go",
    "python/cpython": "python",
    "kubernetes/kubernetes": "kubernetes",
    "django/django": "django",
    "pallets/flask": "flask",
    "tiangolo/fastapi": "fastapi",
    "reactor/reactor-core": "project-reactor",
    "reactos/reactos": None,
}

_FEATURE_ENTRIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("xss", "XSS", ("xss", "cross-site scripting")),
    ("sql-injection", "SQL injection", ("sql injection", "sqli")),
    ("authorization-bypass", "Authorization bypass", ("authorization bypass", "authz bypass")),
)

_GHSA_RE = re.compile(
    r"\bGHSA-[23456789cfghjmpqrvwxy]{4}-[23456789cfghjmpqrvwxy]{4}-"
    r"[23456789cfghjmpqrvwxy]{4}\b",
    re.IGNORECASE,
)
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
_OSV_RE = re.compile(r"\bOSV-\d{4}-\d+\b", re.IGNORECASE)
_REPO_RE = re.compile(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b")
_REPO_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_VERSION_AFTER_RE = re.compile(r"^\s*v?(\d+(?:\.\d+){0,3})\b", re.IGNORECASE)
_SOFTWARE_CONTEXT_RE = re.compile(
    r"\b("
    r"release|released|tagged|advisory|advisories|cve|ghsa|osv|npm|pypi|"
    r"crate|crates|maven|gradle|compiler|runtime|library|libraries|framework|"
    r"package|packages|dependency|dependencies|sdk|language|languages|"
    r"jvm|jdk|rustc|golang|typescript|javascript|security|module|modules|"
    r"pip|cargo|version|versions|upgrade|migration|jsx|tsx|github|gitlab|"
    r"vulnerability|vulnerabilities|patch|patched|server\s+components?"
    r")\b|v?\d+\.\d+",
    re.IGNORECASE,
)
_COLLISIONS: dict[str, tuple[re.Pattern[str], str]] = {
    "java": (
        re.compile(r"\b(island|earthquake|aftershocks?|geology|java sea)\b", re.IGNORECASE),
        "geographic_or_unrelated_sense",
    ),
    "react": (
        re.compile(
            r"\b(how to react|react during|react under|react to|nuclear reactor|"
            r"reactor containment)\b",
            re.IGNORECASE,
        ),
        "verb_or_unrelated_lexical_collision",
    ),
    "go": (
        re.compile(r"\b(pok[eé]mon\s+go|let'?s go|go to the)\b", re.IGNORECASE),
        "unrelated_lexical_collision",
    ),
    "swift": (
        re.compile(r"\b(interbank|settlement|swift network)\b", re.IGNORECASE),
        "unrelated_financial_network",
    ),
    "rust": (
        re.compile(
            r"\b(iron rust|rust (?:on|conversion|coating)|corrosion|outdoor steel)\b",
            re.IGNORECASE,
        ),
        "corrosion_sense",
    ),
}

WEIGHT_STRUCTURED = 1.0
WEIGHT_STRUCTURED_LINKED = 0.9
WEIGHT_VERSIONED = 0.85
WEIGHT_PROSE = 0.7
WEIGHT_FEATURE = 0.45


@dataclass(frozen=True)
class StructuredIdentifiers:
    ghsa_ids: tuple[str, ...] = ()
    cve_ids: tuple[str, ...] = ()
    osv_ids: tuple[str, ...] = ()
    repository: str | None = None
    packages: tuple[str, ...] = ()
    package_names: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> StructuredIdentifiers:
        if not data:
            return cls()
        repository = data.get("repository")
        return cls(
            ghsa_ids=_unique_upper(data.get("ghsa_ids")),
            cve_ids=_unique_upper(data.get("cve_ids")),
            osv_ids=_unique_upper(data.get("osv_ids")),
            repository=(
                str(repository).strip()
                if isinstance(repository, str) and repository.strip()
                else None
            ),
            packages=_unique_text(data.get("packages")),
            package_names=_unique_text(data.get("package_names")),
        )


@dataclass(frozen=True)
class EventConceptInput:
    event_id: str = ""
    source_type: str = ""
    source_key: str = ""
    title: str = ""
    summary: str = ""
    delta_summaries: tuple[str, ...] = ()
    structured: StructuredIdentifiers = field(default_factory=StructuredIdentifiers)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> EventConceptInput:
        deltas = data.get("delta_summaries") or data.get("deltas") or ()
        if isinstance(deltas, str):
            delta_summaries = (deltas,)
        else:
            delta_summaries = tuple(str(item) for item in deltas if isinstance(item, str))
        return cls(
            event_id=str(data.get("event_id") or ""),
            source_type=str(data.get("source_type") or ""),
            source_key=str(data.get("source_key") or ""),
            title=str(data.get("title") or ""),
            summary=str(data.get("summary") or ""),
            delta_summaries=delta_summaries,
            structured=StructuredIdentifiers.from_mapping(
                data.get("structured") if isinstance(data.get("structured"), Mapping) else None
            ),
        )


@dataclass(frozen=True)
class EventConcept:
    concept_id: str
    canonical_name: str
    concept_type: ConceptType
    weight: float
    confidence: Confidence
    stable_id: str | None
    aliases: tuple[str, ...]
    product_version: str | None
    source: ConceptSource
    provenance: str

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "canonical_name": self.canonical_name,
            "concept_type": self.concept_type,
            "weight": self.weight,
            "confidence": self.confidence,
            "stable_id": self.stable_id,
            "aliases": list(self.aliases),
            "product_version": self.product_version,
            "source": self.source,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class ConceptAbstention:
    raw_text: str
    reason: str
    candidate_concept_id: str | None
    provenance: str

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "reason": self.reason,
            "candidate_concept_id": self.candidate_concept_id,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class RelationConceptFeatures:
    version: str
    concept_ids: tuple[str, ...]
    canonical_names: tuple[str, ...]
    stable_ids: tuple[str, ...]
    aliases: tuple[str, ...]
    types: tuple[str, ...]
    weights: tuple[float, ...]

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "concept_ids": list(self.concept_ids),
            "canonical_names": list(self.canonical_names),
            "stable_ids": list(self.stable_ids),
            "aliases": list(self.aliases),
            "types": list(self.types),
            "weights": list(self.weights),
        }


@dataclass(frozen=True)
class EventConceptExtraction:
    version: str
    event_id: str
    concepts: tuple[EventConcept, ...]
    abstentions: tuple[ConceptAbstention, ...]

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "event_id": self.event_id,
            "concepts": [concept.to_snapshot() for concept in self.concepts],
            "abstentions": [item.to_snapshot() for item in self.abstentions],
        }

    def features_for_relation(self) -> RelationConceptFeatures:
        return RelationConceptFeatures(
            version=self.version,
            concept_ids=tuple(concept.concept_id for concept in self.concepts),
            canonical_names=tuple(concept.canonical_name for concept in self.concepts),
            stable_ids=tuple(concept.stable_id for concept in self.concepts if concept.stable_id),
            aliases=tuple(alias for concept in self.concepts for alias in concept.aliases),
            types=tuple(concept.concept_type for concept in self.concepts),
            weights=tuple(concept.weight for concept in self.concepts),
        )


@dataclass(frozen=True)
class _LexiconEntry:
    concept_id: str
    canonical_name: str
    concept_type: ConceptType
    aliases: tuple[str, ...]
    ambiguous: bool
    stable_id: str | None = None


@dataclass
class _Candidate:
    concept_id: str
    canonical_name: str
    concept_type: ConceptType
    weight: float
    confidence: Confidence
    stable_id: str | None
    aliases: list[str]
    product_version: str | None
    source: ConceptSource
    provenance: str
    field: str


def extract_event_concepts(
    event: EventConceptInput | Mapping[str, Any],
) -> EventConceptExtraction:
    payload = event if isinstance(event, EventConceptInput) else EventConceptInput.from_mapping(event)
    fields = _text_fields(payload)
    combined = " ".join(text for _name, text in fields if text)
    structured = _infer_structured(payload)

    candidates: list[_Candidate] = []
    abstentions: list[ConceptAbstention] = []

    candidates.extend(_extract_structured_identifiers(structured))
    prose_ids, prose_id_abstentions = _extract_prose_identifiers(
        fields,
        structured=structured,
    )
    candidates.extend(prose_ids)
    abstentions.extend(prose_id_abstentions)
    catalog_candidates, catalog_abstentions = _extract_catalog_concepts(fields, combined)
    candidates.extend(catalog_candidates)
    abstentions.extend(catalog_abstentions)
    candidates.extend(_extract_features(fields))
    candidates.extend(_linked_repo_products(structured))

    merged = _merge_candidates(candidates)
    concepts = tuple(
        EventConcept(
            concept_id=item.concept_id,
            canonical_name=item.canonical_name,
            concept_type=item.concept_type,
            weight=_weight(item.weight),
            confidence=item.confidence,
            stable_id=item.stable_id,
            aliases=tuple(item.aliases),
            product_version=item.product_version,
            source=item.source,
            provenance=item.provenance,
        )
        for item in merged
    )
    unique_abstentions = _unique_abstentions(abstentions)
    return EventConceptExtraction(
        version=EVENT_CONCEPT_VERSION,
        event_id=payload.event_id,
        concepts=concepts,
        abstentions=unique_abstentions,
    )


def rebuild_event_concepts(event: EventConceptInput | Mapping[str, Any]) -> EventConceptExtraction:
    return extract_event_concepts(event)


def to_snapshot(extraction: EventConceptExtraction) -> dict[str, Any]:
    return extraction.to_snapshot()


def features_for_relation(extraction: EventConceptExtraction) -> RelationConceptFeatures:
    return extraction.features_for_relation()


def extraction_from_snapshot(data: Mapping[str, Any]) -> EventConceptExtraction:
    concepts = tuple(
        EventConcept(
            concept_id=str(item["concept_id"]),
            canonical_name=str(item["canonical_name"]),
            concept_type=item["concept_type"],
            weight=float(item["weight"]),
            confidence=item["confidence"],
            stable_id=item.get("stable_id"),
            aliases=tuple(item.get("aliases") or ()),
            product_version=item.get("product_version"),
            source=item["source"],
            provenance=str(item["provenance"]),
        )
        for item in data.get("concepts") or ()
    )
    abstentions = tuple(
        ConceptAbstention(
            raw_text=str(item["raw_text"]),
            reason=str(item["reason"]),
            candidate_concept_id=item.get("candidate_concept_id"),
            provenance=str(item["provenance"]),
        )
        for item in data.get("abstentions") or ()
    )
    return EventConceptExtraction(
        version=str(data.get("version") or EVENT_CONCEPT_VERSION),
        event_id=str(data.get("event_id") or ""),
        concepts=concepts,
        abstentions=abstentions,
    )


def _text_fields(payload: EventConceptInput) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = [
        ("source_key", payload.source_key),
        ("title", payload.title),
        ("summary", payload.summary),
    ]
    for index, delta in enumerate(payload.delta_summaries):
        fields.append((f"delta.{index}", delta))
    return tuple(fields)


def _infer_structured(payload: EventConceptInput) -> StructuredIdentifiers:
    explicit = payload.structured
    ghsa_ids = list(explicit.ghsa_ids)
    cve_ids = list(explicit.cve_ids)
    osv_ids = list(explicit.osv_ids)
    repository = explicit.repository
    source_key = payload.source_key.strip()
    source_type = payload.source_type

    if source_type in _STRUCTURED_REPO_TYPES and _REPO_KEY_RE.match(source_key):
        repository = repository or source_key
    if source_type in _STRUCTURED_ADVISORY_TYPES:
        if _GHSA_RE.fullmatch(source_key):
            ghsa_ids.append(source_key.upper())
        elif _CVE_RE.fullmatch(source_key):
            cve_ids.append(source_key.upper())
        elif _OSV_RE.fullmatch(source_key):
            osv_ids.append(source_key.upper())

    return StructuredIdentifiers(
        ghsa_ids=tuple(dict.fromkeys(item.upper() for item in ghsa_ids if item)),
        cve_ids=tuple(dict.fromkeys(item.upper() for item in cve_ids if item)),
        osv_ids=tuple(dict.fromkeys(item.upper() for item in osv_ids if item)),
        repository=repository,
        packages=explicit.packages,
        package_names=explicit.package_names,
    )


def _extract_structured_identifiers(structured: StructuredIdentifiers) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for ghsa in structured.ghsa_ids:
        candidates.append(
            _identifier_candidate(
                kind="ghsa",
                value=ghsa,
                raw=ghsa,
                field="structured.ghsa_ids",
                source="structured",
            )
        )
    for cve in structured.cve_ids:
        candidates.append(
            _identifier_candidate(
                kind="cve",
                value=cve,
                raw=cve,
                field="structured.cve_ids",
                source="structured",
            )
        )
    for osv in structured.osv_ids:
        candidates.append(
            _identifier_candidate(
                kind="osv",
                value=osv,
                raw=osv,
                field="structured.osv_ids",
                source="structured",
            )
        )
    if structured.repository:
        candidates.append(
            _repository_candidate(
                structured.repository,
                field="structured.repository",
                source="structured",
            )
        )
    for package in structured.packages:
        candidates.append(_package_candidate(package, field="structured.packages", source="structured"))
    for name in structured.package_names:
        candidates.append(
            _package_candidate(name, field="structured.package_names", source="structured", name_only=True)
        )
    return candidates


def _extract_prose_identifiers(
    fields: Sequence[tuple[str, str]],
    *,
    structured: StructuredIdentifiers,
) -> tuple[list[_Candidate], list[ConceptAbstention]]:
    structured_ghsa = set(structured.ghsa_ids)
    structured_cve = set(structured.cve_ids)
    structured_osv = set(structured.osv_ids)
    structured_repo = structured.repository.casefold() if structured.repository else None
    candidates: list[_Candidate] = []
    abstentions: list[ConceptAbstention] = []

    for field_name, text in fields:
        if field_name == "source_key":
            continue
        for raw in _GHSA_RE.findall(text):
            value = raw.upper()
            if structured_ghsa and value not in structured_ghsa:
                abstentions.append(
                    ConceptAbstention(
                        raw_text=raw,
                        reason="structured_identifier_override",
                        candidate_concept_id=f"ghsa:{value}",
                        provenance=_provenance("prose", field_name),
                    )
                )
                continue
            if structured_ghsa:
                continue
            candidates.append(
                _identifier_candidate(kind="ghsa", value=value, raw=raw, field=field_name, source="prose")
            )
        for raw in _CVE_RE.findall(text):
            value = raw.upper()
            if structured_cve and value not in structured_cve:
                abstentions.append(
                    ConceptAbstention(
                        raw_text=raw,
                        reason="structured_identifier_override",
                        candidate_concept_id=f"cve:{value}",
                        provenance=_provenance("prose", field_name),
                    )
                )
                continue
            if structured_cve:
                continue
            candidates.append(
                _identifier_candidate(kind="cve", value=value, raw=raw, field=field_name, source="prose")
            )
        for raw in _OSV_RE.findall(text):
            value = raw.upper()
            if structured_osv and value not in structured_osv:
                abstentions.append(
                    ConceptAbstention(
                        raw_text=raw,
                        reason="structured_identifier_override",
                        candidate_concept_id=f"osv:{value}",
                        provenance=_provenance("prose", field_name),
                    )
                )
                continue
            if structured_osv:
                continue
            candidates.append(
                _identifier_candidate(kind="osv", value=value, raw=raw, field=field_name, source="prose")
            )
        if structured_repo:
            for raw in _REPO_RE.findall(text):
                if raw.casefold() != structured_repo and _looks_like_repository(raw):
                    abstentions.append(
                        ConceptAbstention(
                            raw_text=raw,
                            reason="structured_identifier_override",
                            candidate_concept_id=f"repo:{raw.casefold()}",
                            provenance=_provenance("prose", field_name),
                        )
                    )
    return candidates, abstentions


def _extract_catalog_concepts(
    fields: Sequence[tuple[str, str]],
    combined: str,
) -> tuple[list[_Candidate], list[ConceptAbstention]]:
    lexicon = _lexicon()
    occupied: dict[str, list[tuple[int, int]]] = {name: [] for name, _text in fields}
    matches: list[tuple[int, str, re.Match[str], _LexiconEntry, str]] = []
    for field_name, text in fields:
        if not text or field_name == "source_key":
            continue
        for entry in lexicon:
            for alias in entry.aliases:
                if _alias_key(alias) in _PROSE_SKIP_ALIASES:
                    continue
                pattern = _alias_regex(alias)
                for match in pattern.finditer(text):
                    matches.append((len(match.group(0)), field_name, match, entry, alias))
    matches.sort(key=lambda item: (-item[0], item[1], item[2].start(), item[3].concept_id))

    candidates: list[_Candidate] = []
    abstentions: list[ConceptAbstention] = []
    has_software_context = bool(_SOFTWARE_CONTEXT_RE.search(combined))

    for _length, field_name, match, entry, _alias in matches:
        raw = match.group(0)
        start, end = match.span()
        if _overlaps(occupied[field_name], start, end):
            continue
        collision = _COLLISIONS.get(entry.concept_id)
        if collision is not None and collision[0].search(combined):
            occupied[field_name].append((start, end))
            abstentions.append(
                ConceptAbstention(
                    raw_text=raw,
                    reason=collision[1],
                    candidate_concept_id=entry.concept_id,
                    provenance=_provenance("prose", field_name),
                )
            )
            continue
        if entry.ambiguous and not has_software_context:
            occupied[field_name].append((start, end))
            abstentions.append(
                ConceptAbstention(
                    raw_text=raw,
                    reason="ambiguous_without_software_context",
                    candidate_concept_id=entry.concept_id,
                    provenance=_provenance("prose", field_name),
                )
            )
            continue
        occupied[field_name].append((start, end))
        version = _version_after(match.string, end)
        weight = WEIGHT_VERSIONED if version else WEIGHT_PROSE
        confidence: Confidence = "high" if version or has_software_context else "medium"
        candidates.append(
            _Candidate(
                concept_id=entry.concept_id,
                canonical_name=entry.canonical_name,
                concept_type=entry.concept_type,
                weight=weight,
                confidence=confidence,
                stable_id=entry.stable_id,
                aliases=[raw],
                product_version=version,
                source="prose",
                provenance=_provenance("prose", field_name),
                field=field_name,
            )
        )
    return candidates, abstentions


def _extract_features(fields: Sequence[tuple[str, str]]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for concept_id, canonical, aliases in _FEATURE_ENTRIES:
        pattern = re.compile(
            r"(?<!\w)(" + "|".join(re.escape(alias) for alias in aliases) + r")(?!\w)",
            re.IGNORECASE,
        )
        for field_name, text in fields:
            if field_name == "source_key":
                continue
            match = pattern.search(text)
            if match is None:
                continue
            candidates.append(
                _Candidate(
                    concept_id=concept_id,
                    canonical_name=canonical,
                    concept_type="feature_capability",
                    weight=WEIGHT_FEATURE,
                    confidence="medium",
                    stable_id=None,
                    aliases=[match.group(0)],
                    product_version=None,
                    source="prose",
                    provenance=_provenance("prose", field_name),
                    field=field_name,
                )
            )
            break
    return candidates


def _linked_repo_products(structured: StructuredIdentifiers) -> list[_Candidate]:
    if not structured.repository:
        return []
    product_id = _REPO_PRODUCTS.get(structured.repository.casefold())
    if not product_id:
        return []
    entry = next((item for item in _lexicon() if item.concept_id == product_id), None)
    if entry is None:
        return []
    return [
        _Candidate(
            concept_id=entry.concept_id,
            canonical_name=entry.canonical_name,
            concept_type=entry.concept_type,
            weight=WEIGHT_STRUCTURED_LINKED,
            confidence="high",
            stable_id=entry.stable_id,
            aliases=[structured.repository],
            product_version=None,
            source="structured",
            provenance=_provenance("structured", "structured.repository"),
            field="structured.repository",
        )
    ]


def _merge_candidates(candidates: Sequence[_Candidate]) -> list[_Candidate]:
    merged: dict[str, _Candidate] = {}
    for candidate in candidates:
        key = candidate.concept_id
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        aliases = list(dict.fromkeys([*existing.aliases, *candidate.aliases]))
        source: ConceptSource = (
            "structured" if "structured" in {existing.source, candidate.source} else "prose"
        )
        if existing.source == "structured":
            stable_id = existing.stable_id
        else:
            stable_id = candidate.stable_id or existing.stable_id
        if candidate.source == "structured" and existing.source != "structured":
            stable_id = candidate.stable_id or existing.stable_id
        if existing.weight > candidate.weight or (
            existing.weight == candidate.weight and existing.source == "structured"
        ):
            winner = existing
            other = candidate
        else:
            winner = candidate
            other = existing
        merged[key] = _Candidate(
            concept_id=winner.concept_id,
            canonical_name=winner.canonical_name,
            concept_type=winner.concept_type,
            weight=max(existing.weight, candidate.weight),
            confidence=_better_confidence(existing.confidence, candidate.confidence),
            stable_id=stable_id,
            aliases=aliases,
            product_version=winner.product_version or other.product_version,
            source=source,
            provenance=winner.provenance,
            field=winner.field,
        )

    packages = [item for item in list(merged.values()) if item.concept_id.startswith("pkg:")]
    for package in packages:
        catalog_id = _catalog_id_for_package(package)
        if catalog_id is None or catalog_id not in merged:
            continue
        catalog = merged[catalog_id]
        merged[catalog_id] = _Candidate(
            concept_id=catalog.concept_id,
            canonical_name=catalog.canonical_name,
            concept_type=catalog.concept_type,
            weight=max(package.weight, catalog.weight, WEIGHT_STRUCTURED_LINKED),
            confidence=_better_confidence(package.confidence, catalog.confidence),
            stable_id=package.stable_id,
            aliases=list(dict.fromkeys([*catalog.aliases, *package.aliases])),
            product_version=package.product_version or catalog.product_version,
            source="structured" if package.source == "structured" else catalog.source,
            provenance=package.provenance if package.source == "structured" else catalog.provenance,
            field=package.field if package.source == "structured" else catalog.field,
        )
        if package.concept_id != catalog_id:
            merged.pop(package.concept_id, None)

    return sorted(merged.values(), key=lambda item: (-item.weight, item.concept_id))


def _catalog_id_for_package(package: _Candidate) -> str | None:
    name = package.canonical_name.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    entry = next((item for item in _lexicon() if _alias_key(item.canonical_name) == _alias_key(name)), None)
    if entry is None:
        entry = next(
            (
                item
                for item in _lexicon()
                if any(_alias_key(alias) == _alias_key(name) for alias in item.aliases)
            ),
            None,
        )
    return None if entry is None else entry.concept_id


def _identifier_candidate(
    *,
    kind: str,
    value: str,
    raw: str,
    field: str,
    source: ConceptSource,
) -> _Candidate:
    stable_id = f"{kind}:{value}"
    return _Candidate(
        concept_id=stable_id,
        canonical_name=value,
        concept_type="vulnerability_advisory",
        weight=WEIGHT_STRUCTURED if source == "structured" else WEIGHT_PROSE,
        confidence="high" if source == "structured" else "medium",
        stable_id=stable_id,
        aliases=[raw],
        product_version=None,
        source=source,
        provenance=_provenance(source, field),
        field=field,
    )


def _repository_candidate(repository: str, *, field: str, source: ConceptSource) -> _Candidate:
    normalized = repository.strip()
    stable_id = f"repo:{normalized.casefold()}"
    return _Candidate(
        concept_id=stable_id,
        canonical_name=normalized,
        concept_type="repository",
        weight=WEIGHT_STRUCTURED if source == "structured" else WEIGHT_PROSE,
        confidence="high" if source == "structured" else "medium",
        stable_id=stable_id,
        aliases=[repository],
        product_version=None,
        source=source,
        provenance=_provenance(source, field),
        field=field,
    )


def _package_candidate(
    raw: str,
    *,
    field: str,
    source: ConceptSource,
    name_only: bool = False,
) -> _Candidate:
    parsed = parse_purl(raw) if raw.startswith("pkg:") else None
    if parsed is not None:
        stable_id = f"pkg:{_purl_name(parsed.purl)}"
        version = parsed.version
        name = parsed.name
    elif raw.startswith("pkg:"):
        core = raw[4:].split("#", 1)[0].split("?", 1)[0]
        name_part, _sep, version = core.partition("@")
        stable_id = f"pkg:{name_part}"
        name = name_part.rsplit("/", 1)[-1]
    elif name_only:
        stable_id = f"pkg:{raw.casefold()}"
        version = None
        name = raw
    else:
        stable_id = f"pkg:{raw.casefold()}"
        version = None
        name = raw
    return _Candidate(
        concept_id=stable_id,
        canonical_name=name,
        concept_type="framework_library_package",
        weight=WEIGHT_STRUCTURED if source == "structured" else WEIGHT_PROSE,
        confidence="high" if source == "structured" else "medium",
        stable_id=stable_id,
        aliases=[raw],
        product_version=version or None,
        source=source,
        provenance=_provenance(source, field),
        field=field,
    )


def _purl_name(purl: str) -> str:
    core = purl[4:].split("#", 1)[0].split("?", 1)[0]
    return core.rsplit("@", 1)[0]


@lru_cache(maxsize=1)
def _lexicon() -> tuple[_LexiconEntry, ...]:
    entries: dict[str, _LexiconEntry] = {}
    aliases_by_name: dict[str, list[str]] = {}
    for _topic_id, name, topic_type in TOPIC_CATALOG:
        concept_id = _concept_id(name)
        aliases_by_name.setdefault(name, [name])
        entries[concept_id] = _LexiconEntry(
            concept_id=concept_id,
            canonical_name=name,
            concept_type=_concept_type_for(name, topic_type),
            aliases=(),
            ambiguous=concept_id in _AMBIGUOUS_CONCEPTS,
        )
    for alias, canonical in TOPIC_ALIASES.items():
        aliases_by_name.setdefault(canonical, [canonical]).append(alias)
    extra = (
        _LexiconEntry(
            concept_id="project-reactor",
            canonical_name="Project Reactor",
            concept_type="framework_library_package",
            aliases=("Project Reactor", "reactor-core", "reactor/reactor-core"),
            ambiguous=False,
        ),
    )
    for entry in extra:
        entries[entry.concept_id] = entry
        aliases_by_name[entry.canonical_name] = list(entry.aliases)

    built: list[_LexiconEntry] = []
    for concept_id, entry in entries.items():
        aliases = tuple(dict.fromkeys(aliases_by_name.get(entry.canonical_name, [entry.canonical_name])))
        built.append(
            _LexiconEntry(
                concept_id=concept_id,
                canonical_name=entry.canonical_name,
                concept_type=entry.concept_type,
                aliases=aliases if entry.aliases == () else tuple(dict.fromkeys([*entry.aliases, *aliases])),
                ambiguous=entry.ambiguous,
                stable_id=entry.stable_id,
            )
        )
    return tuple(sorted(built, key=lambda item: item.concept_id))


def _concept_type_for(name: str, topic_type: str) -> ConceptType:
    if name in _LANGUAGE_RUNTIME:
        return "language_runtime"
    if name in _API_PROTOCOL:
        return "api_protocol"
    if name in _PRODUCT_SERVICE:
        return "product_service"
    if name in _COMPANY_PROJECT or topic_type == "company":
        return "company_project"
    if topic_type == "service":
        return "product_service"
    return "framework_library_package"


def _concept_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _alias_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _alias_regex(alias: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)


def _version_after(text: str, end: int) -> str | None:
    match = _VERSION_AFTER_RE.match(text[end:])
    return match.group(1) if match else None


def _overlaps(spans: Sequence[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < existing_end and end > existing_start for existing_start, existing_end in spans)


def _looks_like_repository(value: str) -> bool:
    if value.count("/") != 1:
        return False
    owner, repo = value.split("/", 1)
    if owner.casefold() in {"http:", "https:", "www"} or "." in owner:
        return False
    return bool(owner and repo)


def _provenance(source: str, field: str) -> str:
    return f"{EVENT_CONCEPT_VERSION}|{source}|{field}"


def _weight(value: float) -> float:
    return round(value, 4)


def _better_confidence(left: Confidence, right: Confidence) -> Confidence:
    order = {"high": 2, "medium": 1, "low": 0}
    return left if order[left] >= order[right] else right


def _unique_upper(values: Any) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str):
        return ()
    return tuple(
        dict.fromkeys(
            str(item).upper() for item in values if isinstance(item, str) and item.strip()
        )
    )


def _unique_text(values: Any) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str):
        return ()
    return tuple(dict.fromkeys(str(item) for item in values if isinstance(item, str) and item.strip()))


def _unique_abstentions(items: Sequence[ConceptAbstention]) -> tuple[ConceptAbstention, ...]:
    seen: set[tuple[str, str, str | None]] = set()
    unique: list[ConceptAbstention] = []
    for item in items:
        key = (item.raw_text.casefold(), item.reason, item.candidate_concept_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)
