"""Replayable semantic user-interest state, independent of Event/Claim world state.

Interest is derived from source signals (topics, selected repositories, inferred
repository technologies/packages, profile text, and feedback). Nothing here
writes observations, claims, events, or deltas. There is no schema revision:
state is versioned by INTEREST_STATE_VERSION plus a fingerprint of the signals
and can be rebuilt at any time.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.db.topic_catalog import canonical_topic

INTEREST_STATE_VERSION = "user-interest-v1"

SignalKind = Literal[
    "explicit_topic",
    "selected_repository",
    "inferred_repository_technology",
    "profile_interest",
    "profile_occupation",
    "positive_feedback",
    "negative_feedback",
]
Origin = Literal["explicit", "inferred"]
Polarity = Literal["positive", "negative"]
MatchKind = Literal["direct", "neighbor"]

_EXPLICIT_FLOOR = 0.35
_TOPIC_WEIGHT = {"high": 1.0, "normal": 0.7, "low": 0.4}
_REPO_WEIGHT = 0.85
_INFERRED_WEIGHT = 0.45
_PROFILE_INTEREST_WEIGHT = 0.55
_OCCUPATION_WEIGHT = 0.2
_FEEDBACK_WEIGHT = 0.5
_NEIGHBOR_SCALE = 0.6

_GO_VERSION_RE = re.compile(r"(?<![a-z0-9])go(?:lang)?[\s/._-]*1\.\d")
_ALNUM_BOUNDARY = r"(?<![a-z0-9]){phrase}(?![a-z0-9])"

# Explicit user declarations are never dropped by negative evidence.
_DECLARATION_KINDS = frozenset(
    {"explicit_topic", "selected_repository", "profile_interest"}
)


@dataclass(frozen=True)
class InterestSignal:
    kind: SignalKind
    origin: Origin
    raw_text: str
    concept_id: str
    weight: float
    polarity: Polarity
    provenance: str


@dataclass(frozen=True)
class InterestConcept:
    concept_id: str
    display_name: str
    origin: Origin
    weight: float
    explicit_weight: float
    inferred_weight: float
    negative_weight: float
    aliases: tuple[str, ...]
    neighbors: tuple[str, ...]
    suppressed: bool
    sources: tuple[InterestSignal, ...]


@dataclass(frozen=True)
class UserInterestState:
    version: str
    user_id: str
    tenant_id: str
    signal_fingerprint: str
    concepts: tuple[InterestConcept, ...]

    def concept_map(self) -> dict[str, InterestConcept]:
        return {concept.concept_id: concept for concept in self.concepts}

    def active_concepts(self) -> tuple[InterestConcept, ...]:
        return tuple(concept for concept in self.concepts if not concept.suppressed and concept.weight > 0)

    def explicit_concepts(self) -> tuple[InterestConcept, ...]:
        return tuple(concept for concept in self.concepts if concept.origin == "explicit")

    def inferred_concepts(self) -> tuple[InterestConcept, ...]:
        return tuple(concept for concept in self.concepts if concept.origin == "inferred")


@dataclass(frozen=True)
class ConceptHit:
    concept_id: str
    display_name: str
    match_kind: MatchKind
    origin: Origin
    weight: float
    explanation: str


@dataclass(frozen=True)
class SemanticMatch:
    matched: bool
    score: float
    hits: tuple[ConceptHit, ...]


@dataclass(frozen=True)
class InterestSources:
    topics: tuple[tuple[str, str], ...] = ()
    repositories: tuple[tuple[str, str], ...] = ()
    occupation: str = ""
    profile_interests: tuple[str, ...] = ()
    feedback: tuple[tuple[str, str], ...] = ()
    inferred_technologies: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ConceptSpec:
    concept_id: str
    display_name: str
    aliases: tuple[str, ...]
    neighbors: tuple[str, ...] = ()
    vetoes: tuple[str, ...] = ()
    ambiguous: bool = False
    support: tuple[str, ...] = ()
    extra_patterns: tuple[re.Pattern[str], ...] = ()


def _spec(
    concept_id: str,
    display_name: str,
    aliases: tuple[str, ...],
    neighbors: tuple[str, ...] = (),
    vetoes: tuple[str, ...] = (),
    *,
    ambiguous: bool = False,
    support: tuple[str, ...] = (),
    extra_patterns: tuple[re.Pattern[str], ...] = (),
) -> _ConceptSpec:
    return _ConceptSpec(
        concept_id,
        display_name,
        aliases,
        neighbors,
        vetoes,
        ambiguous,
        support,
        extra_patterns,
    )


# Curated, bidirectional neighbors plus sense vetoes. Broad lexical aliases that
# explode recall (Java the island, reactor, Pokémon GO) are rejected here.
_CONCEPTS: tuple[_ConceptSpec, ...] = (
    _spec(
        "compiler-optimization",
        "compiler optimization",
        ("compiler optimization", "compiler opt", "loop optimization", "induction variable"),
        ("llvm", "llvm-scalar-evolution"),
    ),
    _spec(
        "llvm",
        "LLVM",
        ("llvm", "llvm ir", "llvm pass"),
        ("compiler-optimization", "llvm-scalar-evolution"),
    ),
    _spec(
        "llvm-scalar-evolution",
        "LLVM Scalar Evolution",
        ("llvm scalar evolution", "scalar evolution", "scev"),
        ("compiler-optimization", "llvm"),
    ),
    _spec(
        "react",
        "React",
        ("react", "react.js", "reactjs", "facebook/react"),
        ("nextjs", "react-native", "typescript"),
        ("reactor", "reactos", "nuclear", "iaea", "containment", "how to react"),
    ),
    _spec("react-native", "React Native", ("react native", "react-native"), ("react",)),
    _spec(
        "nextjs",
        "Next.js",
        ("next.js", "nextjs", "vercel/next.js"),
        ("react", "vercel", "typescript"),
    ),
    _spec("typescript", "TypeScript", ("typescript",), ("react", "nextjs", "javascript")),
    _spec("javascript", "JavaScript", ("javascript", "ecmascript"), ("typescript", "react")),
    _spec(
        "go",
        "Go",
        ("golang", "go lang", "golang/go", "go.mod"),
        ("docker", "kubernetes"),
        ("pokemon", "pokémon", "niantic", "poke"),
        ambiguous=True,
        support=("golang", "runtime", "compiler", "module", "crypto", "toolchain", "goreleaser"),
        extra_patterns=(_GO_VERSION_RE,),
    ),
    _spec(
        "java",
        "Java",
        ("java", "jdk", "openjdk"),
        ("spring",),
        ("island", "earthquake", "aftershock", "geology", "tectonic"),
    ),
    _spec("spring", "Spring", ("spring boot", "spring-boot", "springframework", "spring"), ("java",)),
    _spec(
        "rust",
        "Rust",
        ("rust", "rust-lang", "rustc", "cargo"),
        ("webassembly",),
        ("iron", "coating", "corrosion", "fence", "outdoor"),
    ),
    _spec("webassembly", "WebAssembly", ("webassembly", "wasm"), ("rust",)),
    _spec(
        "swift",
        "Swift",
        ("swift", "apple/swift", "swiftui", "swift language"),
        ("ios",),
        ("interbank", "settlement", "payments", "swift network"),
    ),
    _spec("ios", "iOS", ("ios", "iphone", "ipad"), ("swift",)),
    _spec(
        "rails",
        "Ruby on Rails",
        ("rails", "ruby on rails", "rails/rails", "rubyonrails"),
        ("ruby",),
        ("railway", "railroad", "transit"),
        ambiguous=True,
        support=("ruby", "rails/rails", "active job", "activerecord"),
    ),
    _spec("ruby", "Ruby", ("ruby",), ("rails",)),
    _spec(
        "python",
        "Python",
        ("python", "cpython", "pycon"),
        ("django", "fastapi"),
    ),
    _spec("django", "Django", ("django",), ("python", "fastapi")),
    _spec("fastapi", "FastAPI", ("fastapi",), ("python", "django")),
    _spec(
        "kubernetes",
        "Kubernetes",
        ("kubernetes", "k8s", "kubelet", "kube"),
        ("docker", "go", "helm"),
    ),
    _spec("docker", "Docker", ("docker", "moby/moby"), ("kubernetes", "go")),
    _spec("helm", "Helm", ("helm",), ("kubernetes",)),
    _spec("vercel", "Vercel", ("vercel",), ("nextjs", "react")),
    _spec(
        "github-actions",
        "GitHub Actions",
        ("github actions", "github-actions", "actions/runner"),
        ("github",),
    ),
    _spec("github", "GitHub", ("github",), ("github-actions",)),
    _spec(
        "security",
        "security",
        ("security", "cve", "ghsa", "osv", "advisory", "vulnerability"),
        ("cve",),
    ),
    _spec("cve", "CVE", ("cve",), ("security",)),
    _spec("aws", "AWS", ("aws", "amazon web services", "us-east-1"), ()),
    _spec("statuspage", "statuspage", ("statuspage", "status page"), ()),
)

_CONCEPT_BY_ID = {spec.concept_id: spec for spec in _CONCEPTS}

_REPO_INFERRED: dict[str, tuple[str, ...]] = {
    "facebook/react": ("javascript",),
    "vercel/next.js": ("typescript",),
    "kubernetes/kubernetes": ("go",),
    "django/django": ("python",),
    "encode/fastapi": ("python",),
    "rust-lang/rust": (),
    "spring-projects/spring-boot": ("java",),
    "spring-projects/spring-framework": ("java",),
    "rails/rails": ("ruby",),
    "apple/swift": (),
    "moby/moby": ("go",),
    "actions/runner": ("go",),
    "github/advisory-database": ("security",),
}


def _fold(value: str) -> str:
    stripped = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(stripped.casefold().split())


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(value))


def _build_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for spec in _CONCEPTS:
        index[_normalize_key(spec.display_name)] = spec.concept_id
        index[_normalize_key(spec.concept_id)] = spec.concept_id
        for alias in spec.aliases:
            index[_normalize_key(alias)] = spec.concept_id
    return index


_ALIAS_TO_CONCEPT = _build_alias_index()


def _phrase_in(folded: str, phrase: str) -> bool:
    cleaned = _fold(phrase)
    if not cleaned:
        return False
    pattern = _ALNUM_BOUNDARY.format(phrase=re.escape(cleaned))
    return re.search(pattern, folded) is not None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(value)).strip("-")
    return slug or "concept"


def resolve_concept_id(raw_text: str) -> str:
    folded = _fold(raw_text)
    key = _normalize_key(folded)
    if key in _ALIAS_TO_CONCEPT:
        return _ALIAS_TO_CONCEPT[key]
    catalog = canonical_topic(raw_text)
    if catalog is not None:
        catalog_key = _normalize_key(catalog[0])
        if catalog_key in _ALIAS_TO_CONCEPT:
            return _ALIAS_TO_CONCEPT[catalog_key]
        return _slug(catalog[0])
    # Prefer a known alias contained as a full phrase (facebook/react → react).
    for alias, concept_id in sorted(_ALIAS_TO_CONCEPT.items(), key=lambda item: -len(item[0])):
        spec = _CONCEPT_BY_ID[concept_id]
        if any(_phrase_in(folded, name) for name in (spec.display_name, *spec.aliases)):
            if len(alias) >= 4 or concept_id in folded.replace(" ", ""):
                return concept_id
    return _slug(raw_text)


def _display_name(concept_id: str, fallback: str) -> str:
    spec = _CONCEPT_BY_ID.get(concept_id)
    if spec is not None:
        return spec.display_name
    catalog = canonical_topic(fallback)
    if catalog is not None:
        return catalog[0]
    return fallback.strip() or concept_id


def known_concept_ids() -> frozenset[str]:
    return frozenset(_CONCEPT_BY_ID)


def concept_display_name(concept_id: str, fallback: str = "") -> str:
    return _display_name(concept_id, fallback or concept_id)


def concept_neighbors(concept_id: str) -> tuple[str, ...]:
    return _neighbors_of(concept_id)


def concept_vetoes(concept_id: str) -> tuple[str, ...]:
    spec = _CONCEPT_BY_ID.get(concept_id)
    return spec.vetoes if spec is not None else ()


def _neighbors_of(concept_id: str) -> tuple[str, ...]:
    spec = _CONCEPT_BY_ID.get(concept_id)
    return spec.neighbors if spec is not None else ()


def _aliases_of(concept_id: str, fallback: str) -> tuple[str, ...]:
    spec = _CONCEPT_BY_ID.get(concept_id)
    if spec is None:
        return (fallback,)
    return (spec.display_name, *spec.aliases)


def detect_concepts_in_text(text: str) -> tuple[str, ...]:
    folded = _fold(text)
    if not folded:
        return ()
    found: list[str] = []
    for spec in _CONCEPTS:
        if any(_phrase_in(folded, veto) for veto in spec.vetoes):
            continue
        strong = any(_phrase_in(folded, alias) for alias in spec.aliases if len(_fold(alias)) > 3)
        strong = strong or any(pattern.search(folded) for pattern in spec.extra_patterns)
        weak = any(_phrase_in(folded, alias) for alias in spec.aliases if len(_fold(alias)) <= 3)
        if spec.ambiguous and weak and not strong:
            if not any(_phrase_in(folded, hint) for hint in spec.support):
                continue
        if not (strong or weak):
            continue
        found.append(spec.concept_id)
    return tuple(dict.fromkeys(found))


def signals_from_sources(sources: InterestSources) -> tuple[InterestSignal, ...]:
    signals: list[InterestSignal] = []
    for name, priority in sources.topics:
        cleaned = name.strip()
        if not cleaned:
            continue
        concept_id = resolve_concept_id(cleaned)
        signals.append(
            InterestSignal(
                kind="explicit_topic",
                origin="explicit",
                raw_text=cleaned,
                concept_id=concept_id,
                weight=_TOPIC_WEIGHT.get(priority, 0.7),
                polarity="positive",
                provenance=f"topic:{cleaned}:{priority}",
            )
        )
    for full_name, language in sources.repositories:
        repo = full_name.strip()
        if not repo:
            continue
        signals.append(
            InterestSignal(
                kind="selected_repository",
                origin="explicit",
                raw_text=repo,
                concept_id=resolve_concept_id(repo),
                weight=_REPO_WEIGHT,
                polarity="positive",
                provenance=f"repo:{repo}",
            )
        )
        inferred = list(_REPO_INFERRED.get(repo.casefold(), ()))
        if language.strip():
            inferred.append(resolve_concept_id(language))
        for tech in dict.fromkeys(inferred):
            if not tech:
                continue
            signals.append(
                InterestSignal(
                    kind="inferred_repository_technology",
                    origin="inferred",
                    raw_text=f"{repo}:{tech}",
                    concept_id=tech if tech in _CONCEPT_BY_ID else resolve_concept_id(tech),
                    weight=_INFERRED_WEIGHT,
                    polarity="positive",
                    provenance=f"repo-inferred:{repo}:{tech}",
                )
            )
    for raw in sources.inferred_technologies:
        cleaned = raw.strip()
        if not cleaned:
            continue
        signals.append(
            InterestSignal(
                kind="inferred_repository_technology",
                origin="inferred",
                raw_text=cleaned,
                concept_id=resolve_concept_id(cleaned),
                weight=_INFERRED_WEIGHT,
                polarity="positive",
                provenance=f"inferred:{cleaned}",
            )
        )
    occupation = sources.occupation.strip()
    if occupation:
        signals.append(
            InterestSignal(
                kind="profile_occupation",
                origin="explicit",
                raw_text=occupation,
                concept_id=_slug(occupation),
                weight=_OCCUPATION_WEIGHT,
                polarity="positive",
                provenance=f"occupation:{occupation}",
            )
        )
    for interest in sources.profile_interests:
        cleaned = interest.strip()
        if not cleaned:
            continue
        signals.append(
            InterestSignal(
                kind="profile_interest",
                origin="explicit",
                raw_text=cleaned,
                concept_id=resolve_concept_id(cleaned),
                weight=_PROFILE_INTEREST_WEIGHT,
                polarity="positive",
                provenance=f"profile:{cleaned}",
            )
        )
    for text, feedback in sources.feedback:
        cleaned = text.strip()
        if not cleaned or feedback not in {"important", "not_relevant"}:
            continue
        polarity: Polarity = "positive" if feedback == "important" else "negative"
        kind: SignalKind = "positive_feedback" if polarity == "positive" else "negative_feedback"
        detected = detect_concepts_in_text(cleaned)
        targets = detected or (resolve_concept_id(cleaned),)
        for concept_id in targets:
            signals.append(
                InterestSignal(
                    kind=kind,
                    origin="explicit",
                    raw_text=cleaned,
                    concept_id=concept_id,
                    weight=_FEEDBACK_WEIGHT,
                    polarity=polarity,
                    provenance=f"feedback:{feedback}:{concept_id}",
                )
            )
    return tuple(signals)


def _signal_fingerprint(signals: Sequence[InterestSignal]) -> str:
    payload = [
        {
            "kind": signal.kind,
            "origin": signal.origin,
            "raw": signal.raw_text,
            "concept": signal.concept_id,
            "weight": f"{signal.weight:.4f}",
            "polarity": signal.polarity,
            "prov": signal.provenance,
        }
        for signal in sorted(
            signals,
            key=lambda item: (item.kind, item.provenance, item.raw_text, item.concept_id),
        )
    ]
    encoded = json.dumps(
        {"version": INTEREST_STATE_VERSION, "signals": payload},
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def rebuild_user_interest(user_id: str, signals: Sequence[InterestSignal]) -> UserInterestState:
    grouped: dict[str, list[InterestSignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.concept_id, []).append(signal)

    concepts: list[InterestConcept] = []
    for concept_id, group in grouped.items():
        explicit_weight = sum(
            signal.weight
            for signal in group
            if signal.origin == "explicit" and signal.polarity == "positive"
        )
        inferred_weight = sum(
            signal.weight
            for signal in group
            if signal.origin == "inferred" and signal.polarity == "positive"
        )
        negative_weight = sum(signal.weight for signal in group if signal.polarity == "negative")
        declared = any(
            signal.kind in _DECLARATION_KINDS and signal.polarity == "positive" for signal in group
        )
        fallback = next((signal.raw_text for signal in group if signal.raw_text), concept_id)
        if declared or explicit_weight > 0 and any(signal.kind in _DECLARATION_KINDS for signal in group):
            origin: Origin = "explicit"
            weight = max(_EXPLICIT_FLOOR, explicit_weight + 0.2 * inferred_weight - 0.15 * negative_weight)
            suppressed = False
        elif inferred_weight > 0:
            origin = "inferred"
            weight = inferred_weight - negative_weight
            suppressed = weight <= 0
            weight = max(0.0, weight)
        else:
            origin = "explicit" if explicit_weight > 0 else "inferred"
            weight = max(0.0, explicit_weight - negative_weight)
            suppressed = weight <= 0
        concepts.append(
            InterestConcept(
                concept_id=concept_id,
                display_name=_display_name(concept_id, fallback),
                origin=origin,
                weight=round(weight, 4),
                explicit_weight=round(explicit_weight, 4),
                inferred_weight=round(inferred_weight, 4),
                negative_weight=round(negative_weight, 4),
                aliases=_aliases_of(concept_id, fallback),
                neighbors=_neighbors_of(concept_id),
                suppressed=suppressed,
                sources=tuple(group),
            )
        )
    concepts.sort(key=lambda item: (item.origin != "explicit", -item.weight, item.concept_id))
    return UserInterestState(
        version=INTEREST_STATE_VERSION,
        user_id=user_id,
        tenant_id=user_id,
        signal_fingerprint=_signal_fingerprint(signals),
        concepts=tuple(concepts),
    )


def empty_user_interest(user_id: str) -> UserInterestState:
    return rebuild_user_interest(user_id, ())


def reset_user_interest(user_id: str) -> UserInterestState:
    """Return an empty, versioned state. Derived caches are not persisted."""
    return empty_user_interest(user_id)


def collect_interest_sources(connection: sqlite3.Connection, user_id: str) -> InterestSources:
    topics = tuple(
        (row["name"], row["priority"])
        for row in connection.execute(
            """
            SELECT name, priority
            FROM topics
            WHERE user_id = ?
            ORDER BY sort_order, name
            """,
            (user_id,),
        )
    )
    repositories = tuple(
        (row["full_name"], "")
        for row in connection.execute(
            """
            SELECT full_name
            FROM github_repo_watches
            WHERE user_id = ? AND selected = 1
            ORDER BY full_name
            """,
            (user_id,),
        )
    )
    profile = connection.execute(
        "SELECT occupation, interests_json FROM profiles WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    occupation = ""
    profile_interests: tuple[str, ...] = ()
    if profile is not None:
        occupation = profile["occupation"] or ""
        try:
            parsed = json.loads(profile["interests_json"] or "[]")
        except (TypeError, ValueError):
            parsed = []
        if isinstance(parsed, list):
            profile_interests = tuple(str(item) for item in parsed if isinstance(item, str))
    feedback_rows = connection.execute(
        """
        SELECT fb.type AS feedback_type,
               COALESCE(e.title, '') AS event_title,
               COALESCE(e.summary, '') AS event_summary,
               COALESCE(f.title, '') AS item_title
        FROM feedback fb
        JOIN feed_items f ON f.id = fb.feed_item_id AND f.user_id = fb.user_id
        LEFT JOIN events e ON e.id = f.event_id
        WHERE fb.user_id = ?
        ORDER BY fb.created_at, fb.id
        """,
        (user_id,),
    ).fetchall()
    feedback = tuple(
        (
            " ".join(part for part in (row["item_title"], row["event_title"], row["event_summary"]) if part),
            row["feedback_type"],
        )
        for row in feedback_rows
        if row["feedback_type"] in {"important", "not_relevant"}
    )
    return InterestSources(
        topics=topics,
        repositories=repositories,
        occupation=occupation,
        profile_interests=profile_interests,
        feedback=feedback,
    )


def load_user_interest(connection: sqlite3.Connection, user_id: str) -> UserInterestState:
    sources = collect_interest_sources(connection, user_id)
    return rebuild_user_interest(user_id, signals_from_sources(sources))


def interest_concepts_for_user(state: UserInterestState) -> tuple[InterestConcept, ...]:
    return state.concepts


def semantic_match(state: UserInterestState, text: str) -> SemanticMatch:
    detected = detect_concepts_in_text(text)
    folded = _fold(text)
    active = {concept.concept_id: concept for concept in state.active_concepts()}
    hits: list[ConceptHit] = []

    for concept in active.values():
        if concept.concept_id in detected:
            hits.append(
                ConceptHit(
                    concept_id=concept.concept_id,
                    display_name=concept.display_name,
                    match_kind="direct",
                    origin=concept.origin,
                    weight=concept.weight,
                    explanation=f"direct:{concept.concept_id}",
                )
            )
            continue
        if any(_phrase_in(folded, alias) for alias in concept.aliases if _fold(alias)):
            if concept.concept_id in _CONCEPT_BY_ID:
                continue
            hits.append(
                ConceptHit(
                    concept_id=concept.concept_id,
                    display_name=concept.display_name,
                    match_kind="direct",
                    origin=concept.origin,
                    weight=concept.weight,
                    explanation=f"direct-alias:{concept.concept_id}",
                )
            )

    for detected_id in detected:
        if detected_id in active:
            continue
        for concept in active.values():
            if detected_id in concept.neighbors:
                hits.append(
                    ConceptHit(
                        concept_id=detected_id,
                        display_name=_display_name(detected_id, detected_id),
                        match_kind="neighbor",
                        origin=concept.origin,
                        weight=round(concept.weight * _NEIGHBOR_SCALE, 4),
                        explanation=f"neighbor:{concept.concept_id}->{detected_id}",
                    )
                )
                break

    deduped: dict[tuple[str, str], ConceptHit] = {}
    for hit in hits:
        key = (hit.concept_id, hit.match_kind)
        previous = deduped.get(key)
        if previous is None or hit.weight > previous.weight:
            deduped[key] = hit
    ordered = tuple(sorted(deduped.values(), key=lambda item: (-item.weight, item.concept_id)))
    score = round(sum(hit.weight for hit in ordered), 4)
    return SemanticMatch(matched=bool(ordered), score=score, hits=ordered)


def rank_texts(state: UserInterestState, items: Sequence[tuple[str, str]]) -> list[str]:
    scored = [(semantic_match(state, text).score, item_id) for item_id, text in items]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [item_id for _score, item_id in scored]


def state_from_personalization_user(
    user_id: str,
    *,
    occupation: str,
    interests: Sequence[str],
    topics: Sequence[tuple[str, str]],
    repositories: Sequence[tuple[str, str]],
    prior_feedback: Sequence[tuple[str, str]],
) -> UserInterestState:
    sources = InterestSources(
        topics=tuple(topics),
        repositories=tuple(repositories),
        occupation=occupation,
        profile_interests=tuple(interests),
        feedback=tuple(prior_feedback),
    )
    return rebuild_user_interest(user_id, signals_from_sources(sources))
