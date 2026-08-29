"""Ranked topic recommendations from interest, event concepts, and the catalog.

This is distinct from topic search. It never writes topics, feedback, or the
Event/Claim ledger. Cold-start ranking uses the versioned Rec-11 policy:
empty-profile catalog fallback is inferred/catalog, never explicit; GitHub
priors do not need feedback; first feedback is a bounded overlay.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.db.topic_catalog import TOPIC_CATALOG, canonical_topic
from app.services.cold_start_policy import (
    COLD_START_POLICY_VERSION,
    UserCohort,
    bound_first_feedback_items,
    catalog_fallback_items,
    classify_cohort,
    is_first_feedback,
    state_without_feedback,
)
from app.services.event_concepts import EventConcept, extract_event_concepts
from app.services.user_interest import (
    INTEREST_STATE_VERSION,
    Origin,
    UserInterestState,
    concept_display_name,
    concept_vetoes,
    known_concept_ids,
    load_user_interest,
    resolve_concept_id,
    semantic_match,
)

TOPIC_RECOMMENDATION_VERSION = "topic-recommendations-v1"

Provenance = Origin
Confidence = Literal["high", "medium", "low"]

_NEIGHBOR_SCALE = 0.6
_INFERRED_SCALE = 0.75
_EVENT_SCALE = 0.45
_ABSTAIN_SCORE = 0.12
_MAX_NEIGHBORS_PER_CONCEPT = 3
_DEFAULT_LIMIT = 10
_MAX_EVENT_ROWS = 40

# Wrong-sense identities that must not be suggested for a given interest concept.
_CROSS_SENSE_BLOCKLIST: dict[str, frozenset[str]] = {
    "react": frozenset({"project-reactor", "reactos", "reactor", "nuclear"}),
    "go": frozenset({"pokemon-go", "pokemongo"}),
    "java": frozenset({"island-of-java", "java-island"}),
    "rust": frozenset({"iron-rust", "rust-coating"}),
    "swift": frozenset({"swift-network"}),
    "rails": frozenset({"railway", "railroad"}),
}


@dataclass(frozen=True)
class TopicRecommendation:
    topic_id: str
    name: str
    topic_type: str
    score: float
    reason: str
    provenance: Provenance
    already_followed: bool
    confidence: Confidence
    source_signals: tuple[str, ...]


@dataclass(frozen=True)
class TopicRecommendationAbstention:
    name: str
    reason: str
    score: float


@dataclass(frozen=True)
class TopicRecommendationResult:
    version: str
    user_id: str
    tenant_id: str
    interest_version: str
    interest_fingerprint: str
    items: tuple[TopicRecommendation, ...]
    abstentions: tuple[TopicRecommendationAbstention, ...]
    policy_version: str = COLD_START_POLICY_VERSION
    cohort: UserCohort = "empty_profile"


@dataclass
class _Candidate:
    topic_id: str
    name: str
    topic_type: str
    score: float
    reason: str
    provenance: Provenance
    already_followed: bool
    source_signals: list[str]


def catalog_entry_for(value: str) -> tuple[str, str, str] | None:
    """Return (catalog_id, canonical_name, type) when the value maps to the catalog."""
    topic = canonical_topic(value)
    if topic is None:
        return None
    name, topic_type = topic
    for topic_id, catalog_name, catalog_type in TOPIC_CATALOG:
        if catalog_name == name:
            return topic_id, catalog_name, catalog_type
    return None


def topic_identity(value: str) -> str:
    """Stable identity for alias collapse and Gold name matching."""
    catalog = catalog_entry_for(value)
    if catalog is not None:
        return resolve_concept_id(catalog[1])
    return resolve_concept_id(value)


def _emit_identity(concept_id: str, fallback_name: str) -> tuple[str, str, str]:
    catalog = catalog_entry_for(fallback_name) or catalog_entry_for(concept_id)
    if catalog is not None:
        return catalog
    display = concept_display_name(concept_id, fallback_name)
    catalog = catalog_entry_for(display)
    if catalog is not None:
        return catalog
    return f"concept:{concept_id}", display, "technology"


def _is_recommendable_identity(concept_id: str, name: str) -> bool:
    if catalog_entry_for(name) is not None or catalog_entry_for(concept_id) is not None:
        return True
    return concept_id in known_concept_ids()


def _confidence(score: float) -> Confidence:
    if score >= 0.7:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


def _blocked_for_state(state: UserInterestState, concept_id: str, name: str) -> bool:
    folded = name.casefold()
    identity = topic_identity(name)
    for concept in state.active_concepts():
        for veto in concept_vetoes(concept.concept_id):
            veto_folded = veto.casefold()
            if veto_folded and (
                veto_folded == folded
                or veto_folded == concept_id.casefold()
                or veto_folded == identity
                or veto_folded in folded
            ):
                return True
        blocked = _CROSS_SENSE_BLOCKLIST.get(concept.concept_id, frozenset())
        if concept_id in blocked or identity in blocked or folded in blocked:
            return True
    return False


def _merge(existing: _Candidate, incoming: _Candidate) -> _Candidate:
    signals = list(dict.fromkeys([*existing.source_signals, *incoming.source_signals]))
    provenance: Provenance = (
        "explicit" if "explicit" in {existing.provenance, incoming.provenance} else "inferred"
    )
    if incoming.score > existing.score:
        winner = incoming
        loser = existing
    else:
        winner = existing
        loser = incoming
    return _Candidate(
        topic_id=winner.topic_id,
        name=winner.name,
        topic_type=winner.topic_type,
        score=round(max(existing.score, incoming.score), 4),
        reason=winner.reason if winner.score >= loser.score else existing.reason,
        provenance=provenance,
        already_followed=existing.already_followed or incoming.already_followed,
        source_signals=signals,
    )


def _put(bucket: dict[str, _Candidate], candidate: _Candidate) -> None:
    key = topic_identity(candidate.name)
    previous = bucket.get(key)
    bucket[key] = candidate if previous is None else _merge(previous, candidate)


def recommend_topics(
    state: UserInterestState,
    *,
    followed_names: Sequence[str] = (),
    event_concepts: Sequence[EventConcept] = (),
    limit: int = _DEFAULT_LIMIT,
    include_followed: bool = True,
) -> TopicRecommendationResult:
    cohort = classify_cohort(state)
    if is_first_feedback(state):
        base = _recommend_topics_core(
            state_without_feedback(state),
            followed_names=followed_names,
            event_concepts=event_concepts,
            limit=limit,
            include_followed=include_followed,
            cohort=classify_cohort(state_without_feedback(state)),
        )
        incoming = _recommend_topics_core(
            state,
            followed_names=followed_names,
            event_concepts=event_concepts,
            limit=max(limit, _DEFAULT_LIMIT),
            include_followed=include_followed,
            cohort=cohort,
        )
        blended = bound_first_feedback_items(base.items, incoming.items)
        items = _take_recommendations(blended, limit=limit, include_followed=include_followed)
        abstentions = incoming.abstentions
        return TopicRecommendationResult(
            version=TOPIC_RECOMMENDATION_VERSION,
            user_id=state.user_id,
            tenant_id=state.tenant_id,
            interest_version=state.version or INTEREST_STATE_VERSION,
            interest_fingerprint=state.signal_fingerprint,
            items=tuple(items),
            abstentions=abstentions,
            policy_version=COLD_START_POLICY_VERSION,
            cohort=cohort,
        )
    return _recommend_topics_core(
        state,
        followed_names=followed_names,
        event_concepts=event_concepts,
        limit=limit,
        include_followed=include_followed,
        cohort=cohort,
    )


def _recommend_topics_core(
    state: UserInterestState,
    *,
    followed_names: Sequence[str],
    event_concepts: Sequence[EventConcept],
    limit: int,
    include_followed: bool,
    cohort: UserCohort,
) -> TopicRecommendationResult:
    followed = tuple(name.strip() for name in followed_names if name.strip())
    followed_keys = {topic_identity(name) for name in followed}
    active = [concept for concept in state.active_concepts() if _is_recommendable_identity(
        concept.concept_id, concept.display_name
    )]
    bucket: dict[str, _Candidate] = {}
    abstentions: list[TopicRecommendationAbstention] = []

    for concept in active:
        topic_id, name, topic_type = _emit_identity(concept.concept_id, concept.display_name)
        if _blocked_for_state(state, concept.concept_id, name):
            abstentions.append(
                TopicRecommendationAbstention(
                    name=name,
                    reason="hard-negative or vetoed sense",
                    score=concept.weight,
                )
            )
            continue
        scale = 1.0 if concept.origin == "explicit" else _INFERRED_SCALE
        score = round(concept.weight * scale, 4)
        if score < _ABSTAIN_SCORE:
            abstentions.append(
                TopicRecommendationAbstention(
                    name=name,
                    reason="low-confidence interest weight",
                    score=score,
                )
            )
            continue
        source_kind = next((signal.kind for signal in concept.sources), "interest")
        if concept.origin == "explicit":
            reason = f"Matches your explicit interest in {name}"
        else:
            reason = f"Inferred from {source_kind.replace('_', ' ')} signals"
        _put(
            bucket,
            _Candidate(
                topic_id=topic_id,
                name=name,
                topic_type=topic_type,
                score=score,
                reason=reason,
                provenance=concept.origin,
                already_followed=topic_identity(name) in followed_keys,
                source_signals=[
                    f"interest:{concept.concept_id}",
                    *(signal.provenance for signal in concept.sources[:3]),
                ],
            ),
        )

        neighbor_count = 0
        for neighbor_id in concept.neighbors:
            if neighbor_count >= _MAX_NEIGHBORS_PER_CONCEPT:
                break
            neighbor_name = concept_display_name(neighbor_id)
            if not _is_recommendable_identity(neighbor_id, neighbor_name):
                continue
            if _blocked_for_state(state, neighbor_id, neighbor_name):
                abstentions.append(
                    TopicRecommendationAbstention(
                        name=neighbor_name,
                        reason="hard-negative neighbor",
                        score=round(concept.weight * _NEIGHBOR_SCALE, 4),
                    )
                )
                continue
            neighbor_score = round(concept.weight * _NEIGHBOR_SCALE, 4)
            if neighbor_score < _ABSTAIN_SCORE:
                abstentions.append(
                    TopicRecommendationAbstention(
                        name=neighbor_name,
                        reason="low-confidence semantic neighbor",
                        score=neighbor_score,
                    )
                )
                continue
            n_id, n_name, n_type = _emit_identity(neighbor_id, neighbor_name)
            _put(
                bucket,
                _Candidate(
                    topic_id=n_id,
                    name=n_name,
                    topic_type=n_type,
                    score=neighbor_score,
                    reason=f"Semantic neighbor of {concept.display_name}",
                    provenance="inferred",
                    already_followed=topic_identity(n_name) in followed_keys,
                    source_signals=[f"neighbor:{concept.concept_id}->{neighbor_id}"],
                ),
            )
            neighbor_count += 1

    for event_concept in event_concepts:
        name = event_concept.canonical_name
        concept_id = topic_identity(name) or event_concept.concept_id
        if not _is_recommendable_identity(concept_id, name):
            continue
        if _blocked_for_state(state, event_concept.concept_id, name) or _blocked_for_state(
            state, concept_id, name
        ):
            abstentions.append(
                TopicRecommendationAbstention(
                    name=name,
                    reason="event concept is a hard-negative for this user",
                    score=event_concept.weight,
                )
            )
            continue
        match = semantic_match(state, f"{name} {' '.join(event_concept.aliases)}")
        neighbor_of = any(
            concept_id in concept.neighbors or event_concept.concept_id in concept.neighbors
            for concept in active
        )
        if not match.matched and not neighbor_of:
            continue
        event_score = round(event_concept.weight * _EVENT_SCALE, 4)
        if match.matched:
            event_score = round(max(event_score, match.score * _EVENT_SCALE), 4)
        if event_score < _ABSTAIN_SCORE:
            abstentions.append(
                TopicRecommendationAbstention(
                    name=name,
                    reason="low-confidence event concept",
                    score=event_score,
                )
            )
            continue
        topic_id, catalog_name, topic_type = _emit_identity(concept_id, name)
        _put(
            bucket,
            _Candidate(
                topic_id=topic_id,
                name=catalog_name,
                topic_type=topic_type,
                score=event_score,
                reason=f"Appears in events related to your interests ({name})",
                provenance="inferred",
                already_followed=topic_identity(catalog_name) in followed_keys,
                source_signals=[f"event-concept:{event_concept.concept_id}:{event_concept.provenance}"],
            ),
        )

    if not bucket:
        for fallback in catalog_fallback_items(cohort):
            _put(
                bucket,
                _Candidate(
                    topic_id=fallback.topic_id,
                    name=fallback.name,
                    topic_type=fallback.topic_type,
                    score=fallback.score,
                    reason=fallback.reason,
                    provenance="inferred",
                    already_followed=topic_identity(fallback.name) in followed_keys,
                    source_signals=list(fallback.source_signals),
                ),
            )

    ranked = sorted(bucket.values(), key=lambda item: (-item.score, item.name.casefold()))
    built = [
        TopicRecommendation(
            topic_id=candidate.topic_id,
            name=candidate.name,
            topic_type=candidate.topic_type,
            score=candidate.score,
            reason=candidate.reason,
            provenance=candidate.provenance,
            already_followed=candidate.already_followed,
            confidence=_confidence(candidate.score),
            source_signals=tuple(candidate.source_signals),
        )
        for candidate in ranked
    ]
    items = _take_recommendations(built, limit=limit, include_followed=include_followed)

    return TopicRecommendationResult(
        version=TOPIC_RECOMMENDATION_VERSION,
        user_id=state.user_id,
        tenant_id=state.tenant_id,
        interest_version=state.version or INTEREST_STATE_VERSION,
        interest_fingerprint=state.signal_fingerprint,
        items=tuple(items),
        abstentions=tuple(abstentions),
        policy_version=COLD_START_POLICY_VERSION,
        cohort=cohort,
    )


def _take_recommendations(
    items: Sequence[TopicRecommendation],
    *,
    limit: int,
    include_followed: bool,
) -> list[TopicRecommendation]:
    taken: list[TopicRecommendation] = []
    for item in items:
        if item.already_followed and not include_followed:
            continue
        taken.append(item)
        if len(taken) >= limit:
            break
    return taken


def load_user_event_concepts(
    connection: sqlite3.Connection,
    user_id: str,
    *,
    limit: int = _MAX_EVENT_ROWS,
) -> tuple[EventConcept, ...]:
    rows = connection.execute(
        """
        SELECT e.id, e.title, e.summary, e.current_summary
        FROM events e
        WHERE e.id IN (
            SELECT event_id FROM feed_items WHERE user_id = ?
            UNION
            SELECT event_id FROM event_follows WHERE user_id = ? AND following = 1
        )
        ORDER BY e.updated_at DESC, e.id DESC
        LIMIT ?
        """,
        (user_id, user_id, limit),
    ).fetchall()
    concepts: list[EventConcept] = []
    seen: set[str] = set()
    for row in rows:
        extraction = extract_event_concepts(
            {
                "event_id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "delta_summaries": (row["current_summary"],),
            }
        )
        for concept in extraction.concepts:
            key = f"{concept.concept_id}:{concept.canonical_name.casefold()}"
            if key in seen:
                continue
            seen.add(key)
            concepts.append(concept)
    return tuple(concepts)


def recommend_topics_for_user(
    connection: sqlite3.Connection,
    user_id: str,
    *,
    limit: int = _DEFAULT_LIMIT,
    include_followed: bool = True,
) -> TopicRecommendationResult:
    state = load_user_interest(connection, user_id)
    followed = tuple(
        row["name"]
        for row in connection.execute(
            "SELECT name FROM topics WHERE user_id = ? ORDER BY sort_order, name",
            (user_id,),
        )
    )
    event_concepts = load_user_event_concepts(connection, user_id)
    return recommend_topics(
        state,
        followed_names=followed,
        event_concepts=event_concepts,
        limit=limit,
        include_followed=include_followed,
    )
