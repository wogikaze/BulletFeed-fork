"""Versioned cold-start ranking fallback for topic recommendations (Rec-11).

Cohorts are derived from interest signals, not from Gold `kind`. Catalog
popularity is a last-resort inferred fallback and cannot be labeled explicit.
First feedback is a bounded score overlay; it does not replace preference state.
This module never writes topics, feedback, or the Event/Claim ledger.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.db.topic_catalog import TOPIC_CATALOG, canonical_topic
from app.services.user_interest import (
    InterestSignal,
    InterestSources,
    UserInterestState,
    rebuild_user_interest,
)

COLD_START_POLICY_VERSION = "cold-start-v1"

UserCohort = Literal[
    "empty_profile",
    "profile_only",
    "topic_selected",
    "github_connected",
    "history_rich",
]

_FEEDBACK_KINDS = frozenset({"positive_feedback", "negative_feedback"})
_REPO_KINDS = frozenset({"selected_repository", "inferred_repository_technology"})

# Catalog scores stay below the explicit-interest floor in user_interest.
CATALOG_FALLBACK_SCORE = 0.18
CATALOG_FALLBACK_STEP = 0.002
EXPLICIT_INTEREST_FLOOR = 0.35
FIRST_FEEDBACK_SCORE_DELTA = 0.08

# Evaluation floors for the Rec-11 cold-start slice (k=5).
PRECISION_AT_5_FLOOR = 0.20
IRRELEVANT_ITEM_RATE_CEILING = 0.80
TOPIC_REC_PRECISION_AT_5_FLOOR = 0.40

# Stable catalog slice when the user has no recommendable interest signals.
COLD_START_CATALOG_FALLBACK: tuple[str, ...] = (
    "Kotlin",
    "Android",
    "React",
    "TypeScript",
    "Python",
    "Go",
    "Rust",
    "Kubernetes",
    "GitHub",
    "AWS",
)


@dataclass(frozen=True)
class CatalogFallbackItem:
    topic_id: str
    name: str
    topic_type: str
    score: float
    reason: str
    provenance: Literal["inferred"]
    source_signals: tuple[str, ...]


def classify_cohort(state: UserInterestState) -> UserCohort:
    """Classify from replayable interest signals."""
    kinds = [signal.kind for concept in state.concepts for signal in concept.sources]
    if any(kind in _FEEDBACK_KINDS for kind in kinds):
        return "history_rich"
    if any(kind in _REPO_KINDS for kind in kinds):
        return "github_connected"
    if any(kind == "explicit_topic" for kind in kinds):
        return "topic_selected"
    if any(kind == "profile_interest" for kind in kinds):
        return "profile_only"
    return "empty_profile"


def classify_cohort_from_sources(sources: InterestSources) -> UserCohort:
    if any(feedback in {"important", "not_relevant"} for _text, feedback in sources.feedback):
        return "history_rich"
    if any(name.strip() for name, _language in sources.repositories) or any(
        tech.strip() for tech in sources.inferred_technologies
    ):
        return "github_connected"
    if any(name.strip() for name, _priority in sources.topics):
        return "topic_selected"
    if any(interest.strip() for interest in sources.profile_interests):
        return "profile_only"
    return "empty_profile"


def classify_personalization_user(
    *,
    topics: Sequence[str],
    repositories: Sequence[str],
    profile_interests: Sequence[str],
    prior_feedback: Sequence[object],
) -> UserCohort:
    if prior_feedback:
        return "history_rich"
    if any(name.strip() for name in repositories):
        return "github_connected"
    if any(name.strip() for name in topics):
        return "topic_selected"
    if any(str(interest).strip() for interest in profile_interests):
        return "profile_only"
    return "empty_profile"


def feedback_event_count(state: UserInterestState) -> int:
    texts = {
        signal.raw_text
        for concept in state.concepts
        for signal in concept.sources
        if signal.kind in _FEEDBACK_KINDS and signal.raw_text
    }
    return len(texts)


def is_first_feedback(state: UserInterestState) -> bool:
    return feedback_event_count(state) == 1


def signals_without_feedback(state: UserInterestState) -> tuple[InterestSignal, ...]:
    return tuple(
        signal
        for concept in state.concepts
        for signal in concept.sources
        if signal.kind not in _FEEDBACK_KINDS
    )


def state_without_feedback(state: UserInterestState) -> UserInterestState:
    """Drop feedback signals and rebuild. Preference declarations stay intact."""
    return rebuild_user_interest(state.user_id, signals_without_feedback(state))


def catalog_fallback_items(cohort: UserCohort) -> tuple[CatalogFallbackItem, ...]:
    items: list[CatalogFallbackItem] = []
    for index, name in enumerate(COLD_START_CATALOG_FALLBACK):
        entry = _catalog_entry(name)
        if entry is None:
            continue
        topic_id, catalog_name, topic_type = entry
        score = round(CATALOG_FALLBACK_SCORE - (index * CATALOG_FALLBACK_STEP), 4)
        items.append(
            CatalogFallbackItem(
                topic_id=topic_id,
                name=catalog_name,
                topic_type=topic_type,
                score=score,
                reason=(
                    f"Catalog fallback for {cohort.replace('_', ' ')} "
                    f"[{COLD_START_POLICY_VERSION}]; labeled inferred/catalog, "
                    "not an explicit interest"
                ),
                provenance="inferred",
                source_signals=(
                    "catalog:fallback",
                    f"policy:{COLD_START_POLICY_VERSION}",
                    f"cohort:{cohort}",
                ),
            )
        )
    return tuple(items)


def catalog_score_cap() -> float:
    return CATALOG_FALLBACK_SCORE


def explicit_outranks_catalog(explicit_score: float, catalog_score: float) -> bool:
    return explicit_score >= EXPLICIT_INTEREST_FLOOR and catalog_score <= CATALOG_FALLBACK_SCORE


def clamp_score_delta(base_score: float, incoming_score: float) -> float:
    delta = max(
        -FIRST_FEEDBACK_SCORE_DELTA,
        min(FIRST_FEEDBACK_SCORE_DELTA, incoming_score - base_score),
    )
    return round(base_score + delta, 4)


def bound_first_feedback_items[TRecommendation](
    base_items: Sequence[TRecommendation],
    incoming_items: Sequence[TRecommendation],
) -> list[TRecommendation]:
    """Blend one feedback event into base ranking without replacing it.

    `base_items` / `incoming_items` are TopicRecommendation-shaped objects
    (topic_id, name, score, provenance, source_signals, ...).
    """
    base_by_key = {_item_key(item): item for item in base_items}
    incoming_by_key = {_item_key(item): item for item in incoming_items}
    keys = list(dict.fromkeys([*base_by_key, *incoming_by_key]))
    blended: list[TRecommendation] = []
    for key in keys:
        base = base_by_key.get(key)
        incoming = incoming_by_key.get(key)
        if base is not None and incoming is not None:
            blended.append(
                replace(
                    base,
                    score=clamp_score_delta(base.score, incoming.score),
                    source_signals=_merge_signals(
                        base.source_signals,
                        incoming.source_signals,
                        extra=("feedback:bounded", f"policy:{COLD_START_POLICY_VERSION}"),
                    ),
                )
            )
        elif base is not None:
            blended.append(base)
        elif incoming is not None:
            blended.append(
                replace(
                    incoming,
                    score=min(incoming.score, FIRST_FEEDBACK_SCORE_DELTA),
                    provenance="inferred",
                    source_signals=_merge_signals(
                        incoming.source_signals,
                        extra=("feedback:bounded", f"policy:{COLD_START_POLICY_VERSION}"),
                    ),
                )
            )
    blended.sort(key=lambda item: (-item.score, item.name.casefold()))
    return blended


def _item_key(item: object) -> str:
    name = getattr(item, "name", "")
    topic_id = getattr(item, "topic_id", "")
    catalog = canonical_topic(str(name))
    if catalog is not None:
        return catalog[0].casefold()
    return str(topic_id or name).casefold()


def _merge_signals(
    *groups: Sequence[str],
    extra: Sequence[str] = (),
) -> tuple[str, ...]:
    merged: list[str] = []
    for group in (*groups, extra):
        for signal in group:
            if signal and signal not in merged:
                merged.append(signal)
    return tuple(merged)


def _catalog_entry(value: str) -> tuple[str, str, str] | None:
    topic = canonical_topic(value)
    if topic is None:
        return None
    name, topic_type = topic
    for topic_id, catalog_name, catalog_type in TOPIC_CATALOG:
        if catalog_name == name:
            return topic_id, catalog_name, catalog_type
    return None
