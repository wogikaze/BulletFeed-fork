from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.services.event_concepts import (
    EventConceptExtraction,
    RelationConceptFeatures,
    extract_event_concepts,
    features_for_relation,
)
from app.services.user_interest import (
    InterestConcept,
    UserInterestState,
    interest_concepts_for_user,
    load_user_interest,
    semantic_match,
)

RELATION_FEATURE_VERSION = "relation-features-v01"
ADJACENT_MIN_SCORE = 0.2
NEIGHBOR_MIN_SCORE = 0.2

_DIRECT_SOURCE_TYPES = frozenset(
    {
        "github_release",
        "github_sbom",
        "osv",
        "github_advisory",
    }
)
_PRIORITY_RANK = {"high": 300, "normal": 200, "low": 100}
_INFERRED_RANK = 80
_PROFILE_RANK = 75
_EXPLICIT_NEIGHBOR_RANK = 60
_INFERRED_NEIGHBOR_RANK = 40
_EXPLICIT_OTHER_RANK = 150
_EXPLICIT_REPO_CONCEPT_RANK = 250
_FEEDBACK_RANK = 150

MatchKind = Literal["direct", "neighbor"]


@dataclass(frozen=True)
class RelationSignal:
    level: str
    reason: str
    matched_topics: tuple[str, ...]
    matched_repositories: tuple[dict[str, str], ...]
    personalization_rank: int = 0
    feature_version: str = RELATION_FEATURE_VERSION
    score: float = 0.0


@dataclass(frozen=True)
class _ConceptMatch:
    concept_id: str
    display_name: str
    match_kind: MatchKind
    origin: str
    weight: float
    provenance: str
    source_kind: str
    rank: int


def evaluate_relation(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    source_type: str,
    source_key: str,
    event_title: str,
    event_summary: str,
) -> RelationSignal:
    repo = _selected_repository(connection, user_id=user_id, source_key=source_key)
    if repo is not None and source_type in _DIRECT_SOURCE_TYPES:
        return _direct_repository_signal(repo)

    interest = load_user_interest(connection, user_id)
    return evaluate_relation_from_state(
        interest,
        source_type=source_type,
        source_key=source_key,
        event_title=event_title,
        event_summary=event_summary,
    )


def evaluate_relation_from_state(
    state: UserInterestState,
    *,
    source_type: str,
    source_key: str,
    event_title: str,
    event_summary: str,
    selected_repository: Mapping[str, str] | None = None,
) -> RelationSignal:
    """Score Relation from a rebuilt interest state plus Event concept features.

    Thresholds and feature version are constants so a replay of the same
    interest fingerprint and Event text yields the same level and rank.
    """
    repo = selected_repository or _repository_from_interest(state, source_key)
    if repo is not None and source_type in _DIRECT_SOURCE_TYPES:
        return _direct_repository_signal(dict(repo))

    extraction = extract_event_concepts(
        {
            "source_type": source_type,
            "source_key": source_key,
            "title": event_title,
            "summary": event_summary,
        }
    )
    features = features_for_relation(extraction)
    text = " ".join(part for part in (source_key, event_title, event_summary) if part)
    return _semantic_relation(state, extraction=extraction, features=features, text=text)


def consume_concept_features(
    features: RelationConceptFeatures | Mapping[str, Any],
) -> tuple[str, ...]:
    """Return match terms from Event concepts without reparsing raw Event prose."""
    payload = features.to_snapshot() if isinstance(features, RelationConceptFeatures) else dict(features)
    terms: list[str] = []
    for key in ("canonical_names", "stable_ids", "concept_ids", "aliases"):
        values = payload.get(key) or ()
        for value in values:
            if isinstance(value, str) and value.strip():
                terms.append(value)
    return tuple(dict.fromkeys(terms))


def _direct_repository_signal(repo: Mapping[str, str]) -> RelationSignal:
    return RelationSignal(
        level="direct",
        reason=f"Directly matches a selected GitHub repository. version={RELATION_FEATURE_VERSION}",
        matched_topics=(),
        matched_repositories=(dict(repo),),
        personalization_rank=1000,
        feature_version=RELATION_FEATURE_VERSION,
        score=1.0,
    )


def _semantic_relation(
    state: UserInterestState,
    *,
    extraction: EventConceptExtraction,
    features: RelationConceptFeatures,
    text: str,
) -> RelationSignal:
    active = [
        concept
        for concept in interest_concepts_for_user(state)
        if not concept.suppressed and concept.weight > 0 and not _feedback_only(concept)
    ]
    if not active:
        return _reference_signal()

    event_terms = consume_concept_features(features)
    event_keys = {_token_key(term) for term in event_terms if _token_key(term)}
    abstained_keys = {
        _token_key(item.candidate_concept_id)
        for item in extraction.abstentions
        if item.candidate_concept_id and _token_key(item.candidate_concept_id)
    }
    matches: list[_ConceptMatch] = []

    for concept in active:
        interest_keys = _interest_keys(concept)
        if interest_keys & abstained_keys:
            continue
        if event_keys and interest_keys & event_keys:
            matches.append(_match_from_concept(concept, match_kind="direct"))
            continue
        neighbor_hit = _neighbor_overlap(concept, event_keys, abstained_keys)
        if neighbor_hit is not None:
            matches.append(neighbor_hit)

    # semantic_match is veto-aware. Use it for catalog gaps (Kotlin, github_release)
    # and curated neighbors (compiler-optimization → LLVM SCEV). Abstentions win.
    for hit in semantic_match(state, text).hits:
        hit_key = _token_key(hit.concept_id)
        if hit_key in abstained_keys:
            continue
        if any(_token_key(item.concept_id) == hit_key for item in matches):
            continue
        if hit.match_kind == "direct":
            concept = next((item for item in active if item.concept_id == hit.concept_id), None)
            if concept is None or _interest_keys(concept) & abstained_keys:
                continue
            matches.append(_match_from_concept(concept, match_kind="direct"))
            continue
        parent = _parent_for_neighbor(active, hit.concept_id)
        if parent is None or parent.origin != "explicit":
            continue
        matches.append(
            _ConceptMatch(
                concept_id=hit.concept_id,
                display_name=hit.display_name,
                match_kind="neighbor",
                origin=parent.origin,
                weight=hit.weight,
                provenance=hit.explanation,
                source_kind=_primary_source_kind(parent),
                rank=_rank_for(
                    origin=parent.origin,
                    match_kind="neighbor",
                    source_kind=_primary_source_kind(parent),
                    priority=_topic_priority(parent),
                ),
            )
        )

    qualifying = [
        item
        for item in matches
        if (item.match_kind == "direct" and item.weight >= ADJACENT_MIN_SCORE)
        or (
            item.match_kind == "neighbor"
            and item.weight >= NEIGHBOR_MIN_SCORE
            and item.origin == "explicit"
        )
    ]
    deduped = _dedupe_matches(qualifying)
    if not deduped:
        return _reference_signal()

    explicit = [item for item in deduped if item.origin == "explicit"]
    chosen = explicit or list(deduped)
    chosen.sort(key=lambda item: (-item.rank, -item.weight, item.display_name.casefold()))
    score = round(sum(item.weight for item in chosen), 4)
    rank = max(item.rank for item in chosen)
    topics = tuple(dict.fromkeys(item.display_name for item in chosen))
    reason = _explain(chosen)
    return RelationSignal(
        level="adjacent",
        reason=reason,
        matched_topics=topics,
        matched_repositories=(),
        personalization_rank=rank,
        feature_version=RELATION_FEATURE_VERSION,
        score=score,
    )


def _match_from_concept(concept: InterestConcept, *, match_kind: MatchKind) -> _ConceptMatch:
    source_kind = _primary_source_kind(concept)
    priority = _topic_priority(concept)
    weight = concept.weight if match_kind == "direct" else round(concept.weight * 0.6, 4)
    provenance = concept.sources[0].provenance if concept.sources else f"interest:{concept.concept_id}"
    return _ConceptMatch(
        concept_id=concept.concept_id,
        display_name=_display_for_match(concept),
        match_kind=match_kind,
        origin=concept.origin,
        weight=weight,
        provenance=provenance,
        source_kind=source_kind,
        rank=_rank_for(
            origin=concept.origin,
            match_kind=match_kind,
            source_kind=source_kind,
            priority=priority,
        ),
    )


def _neighbor_overlap(
    concept: InterestConcept,
    event_keys: set[str],
    abstained_keys: set[str],
) -> _ConceptMatch | None:
    if concept.origin != "explicit" or not event_keys:
        return None
    for neighbor in concept.neighbors:
        key = _token_key(neighbor)
        if not key or key in abstained_keys or key not in event_keys:
            continue
        return _ConceptMatch(
            concept_id=neighbor,
            display_name=neighbor,
            match_kind="neighbor",
            origin=concept.origin,
            weight=round(concept.weight * 0.6, 4),
            provenance=f"neighbor:{concept.concept_id}->{neighbor}",
            source_kind=_primary_source_kind(concept),
            rank=_rank_for(
                origin=concept.origin,
                match_kind="neighbor",
                source_kind=_primary_source_kind(concept),
                priority=_topic_priority(concept),
            ),
        )
    return None


def _parent_for_neighbor(active: Sequence[InterestConcept], neighbor_id: str) -> InterestConcept | None:
    for concept in active:
        if neighbor_id in concept.neighbors:
            return concept
    return None


def _feedback_only(concept: InterestConcept) -> bool:
    """Feedback is a ranking overlay; it must not create Relation adjacency by itself."""
    positive = {signal.kind for signal in concept.sources if signal.polarity == "positive"}
    return positive == {"positive_feedback"}


def _display_for_match(concept: InterestConcept) -> str:
    for signal in concept.sources:
        if signal.kind == "explicit_topic" and signal.raw_text.strip():
            return signal.raw_text.strip()
        if signal.kind == "profile_interest" and signal.raw_text.strip():
            return signal.raw_text.strip()
    return concept.display_name


def _primary_source_kind(concept: InterestConcept) -> str:
    if not concept.sources:
        return "interest"
    preferred = (
        "explicit_topic",
        "selected_repository",
        "profile_interest",
        "profile_occupation",
        "positive_feedback",
        "inferred_repository_technology",
        "negative_feedback",
    )
    kinds = {signal.kind for signal in concept.sources}
    for kind in preferred:
        if kind in kinds:
            return kind
    return concept.sources[0].kind


def _topic_priority(concept: InterestConcept) -> str | None:
    for signal in concept.sources:
        if signal.kind != "explicit_topic":
            continue
        parts = signal.provenance.rsplit(":", 1)
        if len(parts) == 2 and parts[1] in _PRIORITY_RANK:
            return parts[1]
    return None


def _rank_for(
    *,
    origin: str,
    match_kind: MatchKind,
    source_kind: str,
    priority: str | None,
) -> int:
    if match_kind == "neighbor":
        return _EXPLICIT_NEIGHBOR_RANK if origin == "explicit" else _INFERRED_NEIGHBOR_RANK
    if origin == "inferred":
        return _INFERRED_RANK
    if source_kind == "explicit_topic":
        return _PRIORITY_RANK.get(priority or "normal", 200)
    if source_kind == "selected_repository":
        return _EXPLICIT_REPO_CONCEPT_RANK
    if source_kind in {"profile_interest", "profile_occupation"}:
        return _PROFILE_RANK
    if source_kind == "positive_feedback":
        return _FEEDBACK_RANK
    return _EXPLICIT_OTHER_RANK


def _interest_keys(concept: InterestConcept) -> set[str]:
    values = (concept.concept_id, concept.display_name, *concept.aliases)
    return {_token_key(value) for value in values if _token_key(value)}


def _dedupe_matches(matches: Sequence[_ConceptMatch]) -> list[_ConceptMatch]:
    best: dict[str, _ConceptMatch] = {}
    for item in matches:
        key = _token_key(item.concept_id) or item.concept_id
        previous = best.get(key)
        if previous is None:
            best[key] = item
            continue
        if (item.origin == "explicit" and previous.origin != "explicit") or (
            item.origin == previous.origin
            and (item.rank, item.weight) > (previous.rank, previous.weight)
        ):
            best[key] = item
    return list(best.values())


def _explain(matches: Sequence[_ConceptMatch]) -> str:
    parts: list[str] = []
    for item in matches:
        parts.append(
            f"{item.display_name} ({item.origin}/{item.match_kind}, {item.provenance}, "
            f"score={item.weight:.3f})"
        )
    return f"Matches {'; '.join(parts)}. version={RELATION_FEATURE_VERSION}"


def _reference_signal() -> RelationSignal:
    return RelationSignal(
        level="reference",
        reason="",
        matched_topics=(),
        matched_repositories=(),
        personalization_rank=0,
        feature_version=RELATION_FEATURE_VERSION,
        score=0.0,
    )


def _repository_from_interest(
    state: UserInterestState,
    source_key: str,
) -> dict[str, str] | None:
    if not source_key:
        return None
    wanted = source_key.casefold()
    for concept in state.concepts:
        for signal in concept.sources:
            if signal.kind != "selected_repository":
                continue
            if signal.raw_text.casefold() == wanted:
                return {
                    "id": signal.raw_text,
                    "name": signal.raw_text,
                    "url": f"https://github.com/{signal.raw_text}",
                }
    return None


def _selected_repository(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    source_key: str,
) -> dict[str, str] | None:
    if not source_key:
        return None
    row = connection.execute(
        """
        SELECT repository_id, full_name, html_url
        FROM github_repo_watches
        WHERE user_id = ? AND full_name = ? AND selected = 1
        LIMIT 1
        """,
        (user_id, source_key),
    ).fetchone()
    if row is None:
        return None
    full_name = row["full_name"]
    return {
        "id": row["repository_id"],
        "name": full_name,
        "url": row["html_url"] or f"https://github.com/{full_name}",
    }


def _token_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).split())
