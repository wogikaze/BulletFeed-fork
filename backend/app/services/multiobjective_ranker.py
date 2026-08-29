"""Versioned multi-objective feed ranker (Rec-08).

Axes stay separate: relevance (Relation), importance/impact, novelty/knownness,
and a redundancy penalty. Relation is never folded into impact. Uncertain
knownness may demote; it never hides. Near-duplicates are penalized, not deleted.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.evaluation.personalization_gold import (
    PersonalizationGoldCorpus,
    PersonalizationItem,
    PersonalizationUser,
)
from app.services.impact_signals import UNKNOWN, extract_impact_signals, features_for_ranking
from app.services.knowledge_evidence import (
    CONFIDENCE_HIGH,
    STATE_KNOWN,
    STATE_PROBABLY_KNOWN,
    STATE_UNKNOWN,
    VisibilityAction,
)
from app.services.ranking import evaluate_importance
from app.services.relation import evaluate_relation_from_state
from app.services.user_interest import state_from_personalization_user

RANKING_POLICY_VERSION = "multiobjective-ranker-v1"
CURSOR_VERSION = "v5"

PriorityRule = Literal[
    "correction",
    "unresolved_conflict",
    "critical_security",
    "critical_incident",
]

_RELATION_SCORE: dict[str, float] = {"direct": 1.0, "adjacent": 0.55, "reference": 0.08}
_IMPORTANCE_SCORE: dict[str, float] = {"critical": 1.0, "high": 0.75, "medium": 0.42, "low": 0.18}
_NOVELTY_SCORE: dict[str, float] = {
    STATE_UNKNOWN: 1.0,
    STATE_PROBABLY_KNOWN: 0.55,
    STATE_KNOWN: 0.12,
}
_WEIGHTS = {
    "relevance": 0.46,
    "importance": 0.26,
    "novelty": 0.16,
    "urgency": 0.12,
}
_REDUNDANCY_PENALTIES = (0.0, 0.42, 0.72, 0.88)
_TOPIC_OCCUPANCY_PENALTY = 0.18
_TOPIC_OCCUPANCY_AFTER = 2
_PREFERENCE_SCALE = 0.08
_SECURITY_SOURCES = frozenset({"osv", "github_advisory"})
_CORRECTION_DELTAS = frozenset({"correction"})
_CONFLICT_DELTAS = frozenset({"unresolved_contradiction", "unresolved_conflict"})

AXIS_NAMES: tuple[str, ...] = (
    "relevance",
    "importance",
    "novelty",
    "urgency",
    "redundancy_penalty",
    "preference",
)


@dataclass(frozen=True)
class RankerAxes:
    relevance: float
    importance: float
    novelty: float
    urgency: float
    redundancy_penalty: float
    preference: float

    def as_dict(self) -> dict[str, float]:
        return {
            "relevance": self.relevance,
            "importance": self.importance,
            "novelty": self.novelty,
            "urgency": self.urgency,
            "redundancy_penalty": self.redundancy_penalty,
            "preference": self.preference,
        }


@dataclass(frozen=True)
class RankerCandidate:
    item_id: str
    event_id: str = ""
    redundancy_group: str = ""
    topic_key: str = ""
    relation_level: str = "reference"
    relation_score: float = 0.0
    personalization_rank: int = 0
    importance_level: str = "medium"
    impact_snapshot: Mapping[str, Any] | None = None
    knownness_state: str = STATE_UNKNOWN
    knownness_confidence: str = "none"
    delta_type: str = ""
    source_type: str = ""
    updated_at: str = ""
    preference_bonus: float = 0.0


@dataclass(frozen=True)
class RankedItem:
    item_id: str
    policy_version: str
    axes: RankerAxes
    priority_rule: str | None
    priority_tier: int
    composite: float
    visibility: VisibilityAction
    sort_key: tuple[Any, ...]
    hidden: bool = False


@dataclass
class _Scored:
    candidate: RankerCandidate
    relevance: float
    importance: float
    novelty: float
    urgency: float
    preference: float
    priority_rule: str | None
    priority_tier: int
    visibility: VisibilityAction
    base_composite: float
    impact_snapshot: Mapping[str, Any]


def rank_candidates(
    candidates: Sequence[RankerCandidate],
    *,
    policy_version: str = RANKING_POLICY_VERSION,
) -> list[RankedItem]:
    """Rank candidates with inspectable axes and greedy diversity penalties.

    The same inputs and ``policy_version`` always produce the same order.
    Items are never dropped for redundancy. Uncertain knownness never hides.
    """
    if policy_version != RANKING_POLICY_VERSION:
        raise ValueError(f"unknown ranking policy {policy_version}")
    scored = [_score_independent(candidate) for candidate in candidates]
    return _diversify(scored, policy_version=policy_version)


def score_axes(candidate: RankerCandidate) -> RankerAxes:
    """Independent axis scores before diversification (redundancy_penalty is 0)."""
    scored = _score_independent(candidate)
    return RankerAxes(
        relevance=scored.relevance,
        importance=scored.importance,
        novelty=scored.novelty,
        urgency=scored.urgency,
        redundancy_penalty=0.0,
        preference=scored.preference,
    )


def priority_rule_for(candidate: RankerCandidate) -> str | None:
    snapshot = _snapshot_of(candidate)
    signals = _signals(snapshot)
    delta = (candidate.delta_type or "").strip().casefold()
    correction = _signal_value(signals, "correction_or_conflict")
    if delta in _CORRECTION_DELTAS or correction == "correction":
        return "correction"
    if delta in _CONFLICT_DELTAS or correction == "conflict":
        return "unresolved_conflict"
    severity = _signal_value(signals, "security_severity")
    if severity == "critical" or (candidate.source_type in _SECURITY_SOURCES and severity == "high"):
        return "critical_security"
    if _signal_value(signals, "incident_impact") == "critical":
        return "critical_incident"
    return None


def decide_visibility(
    *,
    knownness_state: str,
    knownness_confidence: str,
    priority_rule: str | None = None,
) -> VisibilityAction:
    """Uncertain evidence may show or demote. It must never hide."""
    del priority_rule
    if knownness_state == STATE_PROBABLY_KNOWN:
        return "demote"
    if knownness_state == STATE_KNOWN and knownness_confidence == CONFIDENCE_HIGH:
        return "demote"
    return "show"


def encode_ranking_cursor(item_id: str, *, policy_version: str = RANKING_POLICY_VERSION) -> str:
    raw = f"{CURSOR_VERSION}|{policy_version}|{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_ranking_cursor(
    cursor: str,
    *,
    policy_version: str = RANKING_POLICY_VERSION,
) -> str:
    """Return the last item_id. Reject other ranking versions."""
    padding = "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(cursor + padding).decode()
        version, stored_policy, item_id = decoded.split("|", 2)
        if version != CURSOR_VERSION or stored_policy != policy_version or not item_id:
            raise ValueError
        return item_id
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("cursor is invalid or from an obsolete ranking version") from exc


def paginate_ranked(
    ranked: Sequence[RankedItem],
    *,
    cursor: str | None,
    limit: int,
    policy_version: str = RANKING_POLICY_VERSION,
) -> tuple[list[RankedItem], str | None]:
    start = 0
    if cursor:
        last_id = decode_ranking_cursor(cursor, policy_version=policy_version)
        for index, item in enumerate(ranked):
            if item.item_id == last_id:
                start = index + 1
                break
        else:
            raise ValueError("cursor is invalid or from an obsolete ranking version")
    page = list(ranked[start : start + limit])
    next_cursor = None
    if start + limit < len(ranked) and page:
        next_cursor = encode_ranking_cursor(page[-1].item_id, policy_version=policy_version)
    return page, next_cursor


def rank_personalization_corpus(corpus: PersonalizationGoldCorpus) -> dict[str, list[str]]:
    """Rank Gold items from Relation + impact + redundancy. Does not read labels."""
    items = corpus.item_by_id()
    rankings: dict[str, list[str]] = {}
    for user in corpus.users:
        judged_ids = [row.item_id for row in corpus.judgments_for_user(user.user_id)]
        candidates = [
            candidate_from_gold_item(user, items[item_id]) for item_id in judged_ids if item_id in items
        ]
        ranked = rank_candidates(candidates)
        rankings[user.user_id] = [item.item_id for item in ranked]
    return rankings


def candidate_from_gold_item(
    user: PersonalizationUser,
    item: PersonalizationItem,
    *,
    knownness_state: str = STATE_UNKNOWN,
    knownness_confidence: str = "none",
) -> RankerCandidate:
    """Build a ranker candidate from Gold user/item fields only. No judgment labels."""
    state = state_from_personalization_user(
        user.user_id,
        occupation=user.profile.occupation,
        interests=user.profile.interests,
        topics=tuple((topic.name, topic.priority) for topic in user.topics),
        repositories=tuple((repo.full_name, repo.language) for repo in user.repositories),
        prior_feedback=tuple((row.summary, row.feedback) for row in user.prior_feedback),
    )
    record = gold_item_to_source_record(item)
    relation = evaluate_relation_from_state(
        state,
        source_type=record["source_type"],
        source_key=record["source_key"],
        event_title=item.title,
        event_summary=item.summary,
        selected_repository=_selected_repo(user, record["source_key"]),
    )
    importance = evaluate_importance(
        source_type=record["source_type"],
        delta_type=record["delta_type"],
    )
    snapshot = features_for_ranking(extract_impact_signals(record))
    return RankerCandidate(
        item_id=item.item_id,
        event_id=item.redundancy_group,
        redundancy_group=item.redundancy_group,
        topic_key=item.product,
        relation_level=relation.level,
        relation_score=relation.score,
        personalization_rank=relation.personalization_rank,
        importance_level=importance.level,
        impact_snapshot=snapshot,
        knownness_state=knownness_state,
        knownness_confidence=knownness_confidence,
        delta_type=record["delta_type"],
        source_type=record["source_type"],
        updated_at="",
    )


def gold_item_to_source_record(item: PersonalizationItem) -> dict[str, Any]:
    source_key = item.publisher if "/" in item.publisher else item.product
    if item.kind == "outage":
        delta_type = "state_update"
    else:
        delta_type = "new_fact"
    return {
        "source_type": item.source_family,
        "source_key": source_key,
        "delta_type": delta_type,
        "title": item.title,
        "summary": item.summary,
        "kind": item.kind,
        "product": item.product,
    }


def _score_independent(candidate: RankerCandidate) -> _Scored:
    snapshot = _snapshot_of(candidate)
    relevance = _relevance_score(candidate)
    importance = _importance_score(candidate, snapshot)
    novelty = _novelty_score(candidate)
    urgency = _urgency_score(snapshot, candidate)
    preference = max(-1.0, min(1.0, candidate.preference_bonus)) * _PREFERENCE_SCALE
    rule = priority_rule_for(candidate)
    visibility = decide_visibility(
        knownness_state=candidate.knownness_state,
        knownness_confidence=candidate.knownness_confidence,
        priority_rule=rule,
    )
    tier = _priority_tier(rule, relevance=relevance)
    base = (
        _WEIGHTS["relevance"] * relevance
        + _WEIGHTS["importance"] * importance
        + _WEIGHTS["novelty"] * novelty
        + _WEIGHTS["urgency"] * urgency
        + preference
    )
    return _Scored(
        candidate=candidate,
        relevance=round(relevance, 6),
        importance=round(importance, 6),
        novelty=round(novelty, 6),
        urgency=round(urgency, 6),
        preference=round(preference, 6),
        priority_rule=rule,
        priority_tier=tier,
        visibility=visibility,
        base_composite=round(base, 6),
        impact_snapshot=snapshot,
    )


def _diversify(scored: Sequence[_Scored], *, policy_version: str) -> list[RankedItem]:
    remaining = list(scored)
    selected: list[RankedItem] = []
    group_counts: dict[str, int] = {}
    topic_counts: dict[str, int] = {}
    while remaining:
        best_index = 0
        best_item: RankedItem | None = None
        best_key: tuple[Any, ...] | None = None
        for index, row in enumerate(remaining):
            group = row.candidate.redundancy_group or row.candidate.event_id or row.candidate.item_id
            topic = row.candidate.topic_key
            group_n = group_counts.get(group, 0)
            penalty = _REDUNDANCY_PENALTIES[min(group_n, len(_REDUNDANCY_PENALTIES) - 1)]
            if topic and topic_counts.get(topic, 0) >= _TOPIC_OCCUPANCY_AFTER:
                penalty = min(1.0, penalty + _TOPIC_OCCUPANCY_PENALTY)
            composite = round(row.base_composite - penalty, 6)
            sort_key = (
                row.priority_tier,
                composite,
                row.relevance,
                row.importance,
                row.candidate.personalization_rank,
                row.candidate.updated_at,
                row.candidate.item_id,
            )
            item = RankedItem(
                item_id=row.candidate.item_id,
                policy_version=policy_version,
                axes=RankerAxes(
                    relevance=row.relevance,
                    importance=row.importance,
                    novelty=row.novelty,
                    urgency=row.urgency,
                    redundancy_penalty=round(penalty, 6),
                    preference=row.preference,
                ),
                priority_rule=row.priority_rule,
                priority_tier=row.priority_tier,
                composite=composite,
                visibility=row.visibility,
                sort_key=sort_key,
                hidden=False,
            )
            if best_key is None or sort_key > best_key:
                best_key = sort_key
                best_item = item
                best_index = index
        assert best_item is not None
        selected.append(best_item)
        chosen = remaining.pop(best_index)
        group = chosen.candidate.redundancy_group or chosen.candidate.event_id or chosen.candidate.item_id
        group_counts[group] = group_counts.get(group, 0) + 1
        if chosen.candidate.topic_key:
            topic_counts[chosen.candidate.topic_key] = topic_counts.get(chosen.candidate.topic_key, 0) + 1
    return selected


def _relevance_score(candidate: RankerCandidate) -> float:
    level = _RELATION_SCORE.get(candidate.relation_level, _RELATION_SCORE["reference"])
    score_part = max(0.0, min(1.0, candidate.relation_score)) * 0.2
    rank_part = max(0.0, min(1.0, candidate.personalization_rank / 1000.0)) * 0.1
    return min(1.0, level + score_part + rank_part)


def _importance_score(candidate: RankerCandidate, snapshot: Mapping[str, Any]) -> float:
    """Factual importance only. Relation / knownness / preference are ignored."""
    base = _IMPORTANCE_SCORE.get(candidate.importance_level, _IMPORTANCE_SCORE["medium"])
    signals = _signals(snapshot)
    boost = 0.0
    severity = _signal_value(signals, "security_severity")
    if severity == "critical":
        boost += 0.22
    elif severity == "high":
        boost += 0.12
    incident = _signal_value(signals, "incident_impact")
    if incident == "critical":
        boost += 0.22
    elif incident == "major":
        boost += 0.12
    version = _signal_value(signals, "version_significance")
    if version == "major":
        boost += 0.08
    breaking = _signal_value(signals, "breaking_deprecation_removal")
    if breaking in {"breaking", "removal"}:
        boost += 0.08
    if _signal_value(signals, "correction_or_conflict") in {"correction", "conflict"}:
        boost += 0.16
    return min(1.0, base + boost)


def _novelty_score(candidate: RankerCandidate) -> float:
    return _NOVELTY_SCORE.get(candidate.knownness_state, _NOVELTY_SCORE[STATE_UNKNOWN])


def _urgency_score(snapshot: Mapping[str, Any], candidate: RankerCandidate) -> float:
    signals = _signals(snapshot)
    score = 0.0
    if _signal_value(signals, "correction_or_conflict") in {"correction", "conflict"}:
        score = max(score, 0.95)
    severity = _signal_value(signals, "security_severity")
    if severity == "critical":
        score = max(score, 0.9)
    elif severity == "high":
        score = max(score, 0.7)
    if _signal_value(signals, "incident_recovery") == "unresolved":
        impact = _signal_value(signals, "incident_impact")
        if impact == "critical":
            score = max(score, 0.92)
        elif impact == "major":
            score = max(score, 0.7)
        else:
            score = max(score, 0.45)
    if _signal_value(signals, "deadline") not in {None, UNKNOWN, ""}:
        score = max(score, 0.55)
    if candidate.delta_type in _CORRECTION_DELTAS | _CONFLICT_DELTAS:
        score = max(score, 0.95)
    return score


def _priority_tier(rule: str | None, *, relevance: float) -> int:
    if rule in {"correction", "unresolved_conflict"}:
        return 4
    if rule in {"critical_security", "critical_incident"} and relevance >= 0.35:
        return 3
    return 1


def _snapshot_of(candidate: RankerCandidate) -> Mapping[str, Any]:
    if candidate.impact_snapshot is not None:
        return candidate.impact_snapshot
    return {"version": "", "signals": {}}


def _signals(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    signals = snapshot.get("signals")
    return signals if isinstance(signals, Mapping) else {}


def _signal_value(signals: Mapping[str, Any], name: str) -> Any:
    payload = signals.get(name)
    if isinstance(payload, Mapping):
        return payload.get("value")
    return None


def _selected_repo(user: PersonalizationUser, source_key: str) -> dict[str, str] | None:
    if not source_key:
        return None
    wanted = source_key.casefold()
    for repo in user.repositories:
        if repo.full_name.casefold() == wanted:
            return {
                "id": repo.full_name,
                "name": repo.full_name,
                "url": f"https://github.com/{repo.full_name}",
            }
    return None
