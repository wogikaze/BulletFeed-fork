"""Ranked source candidates from user/topic interest.

Discovery is not evidence. Candidates are ranked recommendations with
provenance; they never write Claims, Observations, or subscriptions.
Hacker News and other aggregators stay discovery_only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from app.database import Database
from app.db.source_discovery_schema import ensure_source_discovery_schema
from app.services.source_catalog import (
    SourceKind,
    get_source_policy,
    source_allows_claim_evidence,
)
from app.services.source_discovery_seeds import (
    CURATED_SOURCE_SEEDS,
    DiscoveryProvenance,
    SourceSeed,
)
from app.services.source_registry import (
    AuthorityStatus,
    Endpoint,
    SourceRegistry,
    VerificationStatus,
    canonicalize_url,
)
from app.services.user_interest import (
    INTEREST_STATE_VERSION,
    InterestSources,
    Origin,
    UserInterestState,
    load_user_interest,
    rebuild_user_interest,
    resolve_concept_id,
    semantic_match,
    signals_from_sources,
)

SOURCE_DISCOVERY_VERSION = "source-discovery-v1"
RecommendationStatus = Literal["pending", "approved", "ignored"]
MatchKind = Literal["direct", "neighbor"]

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 40
_NEIGHBOR_SCALE = 0.55
_INFERRED_SCALE = 0.75
_EXTERNAL_INDEX_SCALE = 0.35
_EXTERNAL_INDEX_CAP = 0.4
_PROVENANCE_RANK = {
    DiscoveryProvenance.CURATED_SEED.value: 0,
    DiscoveryProvenance.REPOSITORY_METADATA.value: 1,
    DiscoveryProvenance.WEBSITE_FEED.value: 2,
    DiscoveryProvenance.STATUSPAGE_LINK.value: 3,
    DiscoveryProvenance.SITEMAP_LINK.value: 4,
    DiscoveryProvenance.PACKAGE_HOMEPAGE.value: 5,
    DiscoveryProvenance.EXTERNAL_INDEX.value: 6,
}


@dataclass(frozen=True)
class DiscoveryHint:
    url: str
    provenance: str
    family: SourceKind | None = None
    concept_ids: tuple[str, ...] = ()
    title: str = ""
    publisher_slug: str | None = None
    publisher_name: str | None = None
    homepage_url: str | None = None
    why: str = ""
    display_name: str = ""


@dataclass(frozen=True)
class SourceCandidate:
    candidate_id: str
    endpoint_id: str
    publisher_id: str
    publisher_slug: str
    publisher_display_name: str
    canonical_url: str
    family: str
    discovery_method: str
    discovery_provenance: str
    verification_status: str
    authority_status: str
    authority_confidence: float
    evidence_eligible: bool
    discovery_only: bool
    match_reason: str
    explanation: str
    matched_concept_ids: tuple[str, ...]
    match_origin: Origin
    match_kind: MatchKind
    score: float
    recommendation_status: RecommendationStatus


@dataclass(frozen=True)
class SourceDiscoveryResult:
    version: str
    user_id: str
    tenant_id: str
    interest_version: str
    interest_fingerprint: str
    items: tuple[SourceCandidate, ...]


def source_candidate_allows_claim_evidence(_candidate: SourceCandidate | None = None) -> bool:
    """Fail closed: a discovery record is never Claim evidence."""
    return False


def discovery_signal_allows_claim_evidence(
    *,
    source_type: str | None = None,
    discovery_provenance: str | None = None,
) -> bool:
    """Fail closed: discovery provenance or discovery-only families cannot back Claims."""
    if discovery_provenance:
        return False
    if source_type is None:
        return False
    return source_allows_claim_evidence(source_type)


def infer_source_family(url: str) -> SourceKind:
    parsed = urlparse(canonicalize_url(url))
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if "ycombinator.com" in host or (
        host.endswith("firebaseio.com") and "hacker-news" in host
    ):
        return SourceKind.HACKER_NEWS_DISCOVERY
    if host.endswith(".statuspage.io") or path.endswith("/api/v2/summary.json"):
        return SourceKind.STATUSPAGE
    if path.endswith("/feed.json") or (path.endswith(".json") and "feed" in path):
        return SourceKind.JSON_FEED
    if any(token in path for token in ("/feed", "/rss", "/atom", ".xml")):
        return SourceKind.RSS_ATOM
    if host in {"github.com", "api.github.com"} and ("/releases" in path or path in {"", "/"}):
        return SourceKind.GITHUB_RELEASE
    return SourceKind.GENERIC_WEB


def hints_from_hacker_news(
    items: Sequence[Mapping[str, Any]],
    state: UserInterestState,
) -> tuple[DiscoveryHint, ...]:
    hints: list[DiscoveryHint] = []
    for item in items:
        title = item.get("title")
        url = item.get("url")
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(url, str) or not url.strip():
            continue
        match = semantic_match(state, title)
        if not match.matched:
            continue
        hints.append(
            DiscoveryHint(
                url=url.strip(),
                provenance=DiscoveryProvenance.EXTERNAL_INDEX.value,
                family=None,
                concept_ids=tuple(hit.concept_id for hit in match.hits),
                title=title.strip(),
                why="Suggested by Hacker News; discovery-only, not Claim evidence",
                display_name=title.strip(),
            )
        )
    return tuple(hints)


def discover_sources(
    state: UserInterestState,
    registry: SourceRegistry | None = None,
    *,
    decisions: Mapping[str, str] | None = None,
    hints: Sequence[DiscoveryHint] = (),
    hn_items: Sequence[Mapping[str, Any]] = (),
    include_ignored: bool = False,
    limit: int = _DEFAULT_LIMIT,
) -> SourceDiscoveryResult:
    source_registry = registry or SourceRegistry()
    merged_hints = (
        *_hints_from_seeds(),
        *_hints_from_selected_repositories(state),
        *hints,
        *hints_from_hacker_news(hn_items, state),
    )
    grouped: dict[str, SourceCandidate] = {}
    for hint in merged_hints:
        candidate = _candidate_from_hint(state, source_registry, hint)
        if candidate is None:
            continue
        existing = grouped.get(candidate.candidate_id)
        grouped[candidate.candidate_id] = (
            candidate if existing is None else _merge_candidates(existing, candidate)
        )

    decision_map = {key: _normalize_decision(value) for key, value in (decisions or {}).items()}
    ranked: list[SourceCandidate] = []
    for candidate in grouped.values():
        status = decision_map.get(candidate.candidate_id, "pending")
        item = replace(candidate, recommendation_status=status)
        if status == "ignored" and not include_ignored:
            continue
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            -item.score,
            -item.authority_confidence,
            _PROVENANCE_RANK.get(item.discovery_provenance, 9),
            item.canonical_url,
        )
    )
    capped = max(1, min(int(limit), _MAX_LIMIT))
    return SourceDiscoveryResult(
        version=SOURCE_DISCOVERY_VERSION,
        user_id=state.user_id,
        tenant_id=state.tenant_id,
        interest_version=state.version or INTEREST_STATE_VERSION,
        interest_fingerprint=state.signal_fingerprint,
        items=tuple(ranked[:capped]),
    )


def discover_sources_for_topics(
    topics: Sequence[str],
    registry: SourceRegistry | None = None,
    **kwargs: Any,
) -> SourceDiscoveryResult:
    cleaned = tuple((topic.strip(), "high") for topic in topics if topic and topic.strip())
    state = rebuild_user_interest(
        "topic-eval",
        signals_from_sources(InterestSources(topics=cleaned)),
    )
    return discover_sources(state, registry, **kwargs)


def discover_sources_for_user(
    connection: sqlite3.Connection,
    user_id: str,
    registry: SourceRegistry | None = None,
    **kwargs: Any,
) -> SourceDiscoveryResult:
    state = load_user_interest(connection, user_id)
    decisions = load_discovery_decisions(connection, user_id)
    return discover_sources(state, registry, decisions=decisions, **kwargs)


def load_discovery_decisions(connection: sqlite3.Connection, user_id: str) -> dict[str, str]:
    try:
        rows = connection.execute(
            """
            SELECT candidate_id, decision
            FROM source_discovery_decisions
            WHERE user_id = ?
            ORDER BY decided_at, candidate_id
            """,
            (user_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row["candidate_id"]: _normalize_decision(row["decision"]) for row in rows}


def save_discovery_decision(
    database: Database,
    *,
    user_id: str,
    candidate_id: str,
    decision: str,
    decided_at: str | None = None,
) -> str:
    ensure_source_discovery_schema(database)
    normalized = _normalize_decision(decision)
    stamp = decided_at or _utc_now()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO source_discovery_decisions (user_id, candidate_id, decision, decided_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, candidate_id) DO UPDATE SET
                decision = excluded.decision,
                decided_at = excluded.decided_at
            """,
            (user_id, candidate_id, normalized, stamp),
        )
    return normalized


def list_source_recommendations_for_user(
    database: Database,
    user_id: str,
    *,
    include_ignored: bool = False,
    limit: int = _DEFAULT_LIMIT,
    hints: Sequence[DiscoveryHint] = (),
    hn_items: Sequence[Mapping[str, Any]] = (),
    registry: SourceRegistry | None = None,
) -> SourceDiscoveryResult:
    ensure_source_discovery_schema(database)
    source_registry = registry or SourceRegistry(database)
    with database.connect() as connection:
        return discover_sources_for_user(
            connection,
            user_id,
            source_registry,
            include_ignored=include_ignored,
            limit=limit,
            hints=hints,
            hn_items=hn_items,
        )


def record_source_recommendation_decision(
    database: Database,
    *,
    user_id: str,
    candidate_id: str,
    decision: str,
) -> SourceCandidate:
    """Record approve/ignore. Does not create a subscription or sync job."""
    ensure_source_discovery_schema(database)
    result = list_source_recommendations_for_user(
        database,
        user_id,
        include_ignored=True,
        limit=_MAX_LIMIT,
    )
    if not any(item.candidate_id == candidate_id for item in result.items):
        raise KeyError(candidate_id)
    save_discovery_decision(database, user_id=user_id, candidate_id=candidate_id, decision=decision)
    updated = list_source_recommendations_for_user(
        database,
        user_id,
        include_ignored=True,
        limit=_MAX_LIMIT,
    )
    for item in updated.items:
        if item.candidate_id == candidate_id:
            return item
    raise KeyError(candidate_id)


def _hints_from_seeds() -> tuple[DiscoveryHint, ...]:
    return tuple(_hint_from_seed(seed) for seed in CURATED_SOURCE_SEEDS)


def _hint_from_seed(seed: SourceSeed) -> DiscoveryHint:
    return DiscoveryHint(
        url=seed.url,
        provenance=seed.provenance,
        family=seed.family,
        concept_ids=seed.concept_ids,
        title=seed.display_name,
        publisher_slug=seed.publisher_slug,
        publisher_name=seed.publisher_name,
        homepage_url=seed.homepage_url,
        why=seed.why,
        display_name=seed.display_name,
    )


def _hints_from_selected_repositories(state: UserInterestState) -> tuple[DiscoveryHint, ...]:
    hints: list[DiscoveryHint] = []
    seen: set[str] = set()
    for concept in state.active_concepts():
        for signal in concept.sources:
            if signal.kind != "selected_repository":
                continue
            repo = signal.raw_text.strip()
            if not repo or repo in seen:
                continue
            seen.add(repo)
            hints.append(
                DiscoveryHint(
                    url=f"https://github.com/{repo}/releases",
                    provenance=DiscoveryProvenance.REPOSITORY_METADATA.value,
                    family=SourceKind.GITHUB_RELEASE,
                    concept_ids=(concept.concept_id, resolve_concept_id(repo)),
                    title=f"{repo} releases",
                    publisher_slug=repo.split("/", 1)[0].lower(),
                    publisher_name=repo,
                    homepage_url=f"https://github.com/{repo}",
                    why=f"Official GitHub releases for selected repository {repo}",
                    display_name=f"{repo} releases",
                )
            )
    return tuple(hints)


def _candidate_from_hint(
    state: UserInterestState,
    registry: SourceRegistry,
    hint: DiscoveryHint,
) -> SourceCandidate | None:
    match = _match_hint(state, hint)
    if match is None:
        return None
    match_kind, origin, concept_ids, interest_weight, match_reason = match
    try:
        family = hint.family or infer_source_family(hint.url)
        canonicalize_url(hint.url)
    except ValueError:
        return None
    verification, authority = _hint_registry_status(hint, family)
    endpoint = _register_or_reuse(
        registry,
        url=hint.url,
        family=family,
        publisher_slug=hint.publisher_slug,
        homepage_url=hint.homepage_url or hint.url,
        publisher_name=hint.publisher_name,
        verification_status=verification,
        authority_status=authority,
    )
    publisher = registry.get_publisher(endpoint.publisher_id)
    publisher_slug = publisher.slug if publisher is not None else (hint.publisher_slug or "unknown")
    publisher_name = (
        publisher.display_name if publisher is not None else (hint.publisher_name or publisher_slug)
    )
    discovery_only = _candidate_is_discovery_only(hint, endpoint)
    authority_confidence = _authority_confidence(endpoint, discovery_only)
    score = _score(interest_weight, match_kind, origin, authority_confidence, hint.provenance)
    explanation = _explanation(hint, endpoint, match_reason, discovery_only)
    return SourceCandidate(
        candidate_id=endpoint.endpoint_id,
        endpoint_id=endpoint.endpoint_id,
        publisher_id=endpoint.publisher_id,
        publisher_slug=publisher_slug,
        publisher_display_name=publisher_name,
        canonical_url=endpoint.canonical_url,
        family=endpoint.family,
        discovery_method=endpoint.discovery_method,
        discovery_provenance=hint.provenance,
        verification_status=endpoint.verification_status,
        authority_status=endpoint.authority_status,
        authority_confidence=authority_confidence,
        evidence_eligible=False,
        discovery_only=discovery_only,
        match_reason=match_reason,
        explanation=explanation,
        matched_concept_ids=concept_ids,
        match_origin=origin,
        match_kind=match_kind,
        score=score,
        recommendation_status="pending",
    )


def _register_or_reuse(
    registry: SourceRegistry,
    *,
    url: str,
    family: SourceKind,
    publisher_slug: str | None,
    homepage_url: str,
    publisher_name: str | None,
    verification_status: str,
    authority_status: str,
) -> Endpoint:
    existing = registry.find_duplicate_endpoint(url, family=family)
    if existing is not None:
        return existing
    if publisher_slug:
        registry.register_publisher(
            slug=publisher_slug,
            display_name=publisher_name or publisher_slug,
            homepage_url=homepage_url,
        )
    return registry.register_endpoint(
        url=url,
        family=family,
        publisher_slug=publisher_slug,
        verification_status=verification_status,
        authority_status=authority_status,
    )


def _hint_registry_status(hint: DiscoveryHint, family: SourceKind) -> tuple[str, str]:
    if hint.provenance == DiscoveryProvenance.EXTERNAL_INDEX.value:
        return VerificationStatus.DISCOVERY_ONLY.value, AuthorityStatus.NON_AUTHORITATIVE.value
    try:
        policy = get_source_policy(family)
    except ValueError:
        return VerificationStatus.UNVERIFIED.value, AuthorityStatus.UNKNOWN.value
    if policy.discovery_only:
        return VerificationStatus.DISCOVERY_ONLY.value, AuthorityStatus.NON_AUTHORITATIVE.value
    return VerificationStatus.VERIFIED.value, (
        AuthorityStatus.AUTHORITATIVE.value if policy.authoritative else AuthorityStatus.UNKNOWN.value
    )


def _candidate_is_discovery_only(hint: DiscoveryHint, endpoint: Endpoint) -> bool:
    if hint.provenance == DiscoveryProvenance.EXTERNAL_INDEX.value:
        return True
    if endpoint.verification_status == VerificationStatus.DISCOVERY_ONLY.value:
        return True
    try:
        return get_source_policy(SourceKind(endpoint.family)).discovery_only
    except ValueError:
        return True


def _match_hint(
    state: UserInterestState,
    hint: DiscoveryHint,
) -> tuple[MatchKind, Origin, tuple[str, ...], float, str] | None:
    active = {concept.concept_id: concept for concept in state.active_concepts()}
    if not active:
        return None
    direct: list[tuple[str, Origin, float]] = []
    neighbor: list[tuple[str, Origin, float]] = []
    for concept_id in hint.concept_ids:
        if concept_id in active:
            concept = active[concept_id]
            direct.append((concept_id, concept.origin, concept.weight))
            continue
        for concept in active.values():
            if concept_id in concept.neighbors:
                neighbor.append((concept_id, concept.origin, concept.weight * _NEIGHBOR_SCALE))
                break
    text = " ".join(
        part
        for part in (hint.display_name, hint.title, hint.why, hint.publisher_name or "")
        if part
    )
    semantic = semantic_match(state, text) if text.strip() else None
    if semantic is not None:
        for hit in semantic.hits:
            if hit.match_kind == "direct":
                direct.append((hit.concept_id, hit.origin, hit.weight))
            else:
                neighbor.append((hit.concept_id, hit.origin, hit.weight))
    if direct:
        concept_ids = tuple(dict.fromkeys(item[0] for item in direct))
        origin = "explicit" if any(item[1] == "explicit" for item in direct) else "inferred"
        weight = max(item[2] for item in direct)
        names = ", ".join(concept_ids)
        reason = f"Matches your {origin} interest in {names}"
        return "direct", origin, concept_ids, weight, reason
    if neighbor:
        concept_ids = tuple(dict.fromkeys(item[0] for item in neighbor))
        origin = "explicit" if any(item[1] == "explicit" for item in neighbor) else "inferred"
        weight = max(item[2] for item in neighbor)
        names = ", ".join(concept_ids)
        reason = f"Related to your {origin} interest via {names}"
        return "neighbor", origin, concept_ids, weight, reason
    return None


def _authority_confidence(endpoint: Endpoint, discovery_only: bool) -> float:
    if discovery_only:
        return 0.12
    if (
        endpoint.verification_status == VerificationStatus.VERIFIED.value
        and endpoint.authority_status == AuthorityStatus.AUTHORITATIVE.value
    ):
        return 0.92
    if endpoint.authority_status == AuthorityStatus.AUTHORITATIVE.value:
        return 0.72
    if endpoint.verification_status == VerificationStatus.VERIFIED.value:
        return 0.64
    return 0.28


def _score(
    interest_weight: float,
    match_kind: MatchKind,
    origin: Origin,
    authority_confidence: float,
    provenance: str,
) -> float:
    base = interest_weight
    if match_kind == "neighbor":
        base *= _NEIGHBOR_SCALE
    if origin == "inferred":
        base *= _INFERRED_SCALE
    score = base * 0.65 + authority_confidence * 0.35
    if provenance == DiscoveryProvenance.EXTERNAL_INDEX.value:
        score = min(_EXTERNAL_INDEX_CAP, score * _EXTERNAL_INDEX_SCALE)
    return round(score, 4)


def _explanation(
    hint: DiscoveryHint,
    endpoint: Endpoint,
    match_reason: str,
    discovery_only: bool,
) -> str:
    how = hint.provenance.replace("_", " ")
    parts = [
        hint.why or hint.display_name or endpoint.canonical_url,
        match_reason,
        f"Discovered via {how}",
        f"family={endpoint.family}",
    ]
    if discovery_only:
        parts.append("Discovery-only: not authoritative and not Claim evidence")
    else:
        parts.append("Verified official sources are preferred; discovery is not evidence")
    return ". ".join(part.rstrip(".") for part in parts if part) + "."


def _merge_candidates(left: SourceCandidate, right: SourceCandidate) -> SourceCandidate:
    preferred, other = (left, right) if _preferred(left, right) else (right, left)
    provenances = tuple(dict.fromkeys((preferred.discovery_provenance, other.discovery_provenance)))
    concepts = tuple(dict.fromkeys((*preferred.matched_concept_ids, *other.matched_concept_ids)))
    extra = ""
    if other.discovery_provenance != preferred.discovery_provenance:
        extra = f" Also seen via {other.discovery_provenance.replace('_', ' ')}."
    return replace(
        preferred,
        matched_concept_ids=concepts,
        score=max(preferred.score, other.score),
        authority_confidence=max(preferred.authority_confidence, other.authority_confidence),
        explanation=preferred.explanation.rstrip(".") + "." + extra,
        discovery_provenance=provenances[0],
        evidence_eligible=False,
        discovery_only=preferred.discovery_only and other.discovery_only,
    )


def _preferred(left: SourceCandidate, right: SourceCandidate) -> bool:
    left_rank = _PROVENANCE_RANK.get(left.discovery_provenance, 9)
    right_rank = _PROVENANCE_RANK.get(right.discovery_provenance, 9)
    if left.discovery_only != right.discovery_only:
        return not left.discovery_only
    if left_rank != right_rank:
        return left_rank < right_rank
    return left.authority_confidence >= right.authority_confidence


def _normalize_decision(value: str) -> RecommendationStatus:
    cleaned = str(value).strip().lower()
    if cleaned in {"approve", "approved"}:
        return "approved"
    if cleaned in {"ignore", "ignored"}:
        return "ignored"
    if cleaned == "pending":
        return "pending"
    raise ValueError(f"unsupported recommendation decision: {value!r}")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

