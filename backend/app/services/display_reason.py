"""User-facing feed-card display reasons (#319).

Reasons are projected from the same inputs the live ranker and cross-source
projection already used. They are not a second ranking policy and must not
invent axes, topics, or knownness facts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.schemas.feed import DisplayDeltaKind, DisplayMatchKind, DisplayReason
from app.services.knowledge_evidence import STATE_PROBABLY_KNOWN, STATE_UNKNOWN
from app.services.multiobjective_ranker import RANKING_POLICY_VERSION

DISPLAY_REASON_POLICY_VERSION: Final = "display-reason-v1"
PersonalizationAdjustment = Literal["boost_importance", "demote_relation"]

_PERSONALIZATION_CODES: Final[dict[PersonalizationAdjustment, str]] = {
    "boost_importance": "personalization.feedback_boost",
    "demote_relation": "personalization.feedback_demote",
}
_PERSONALIZATION_TEXT: Final[dict[PersonalizationAdjustment, str]] = {
    "boost_importance": "これまでの重要マークに合わせて並びを調整しています",
    "demote_relation": "これまでの無関係マークに合わせて並びを調整しています",
}

_CORRECTION_DELTAS = frozenset({"correction"})
_CONFLICT_DELTAS = frozenset({"unresolved_contradiction", "unresolved_conflict", "conflict"})
_DETAIL_DELTAS = frozenset({"detail"})
_STATE_DELTAS = frozenset({"state_update"})
_ASSERTED_KNOWNNESS = ("知っている", "知らない", "未読です", "既知です")


@dataclass(frozen=True)
class DisplayReasonInputs:
    ranking_policy_version: str
    priority_rule: str | None
    redundancy_penalty: float
    relation_level: str
    relation_reason: str
    matched_topics: tuple[str, ...]
    matched_repository_names: tuple[str, ...]
    importance_level: str
    delta_type: str
    knownness_state: str
    knownness_confidence: str
    additional_source_roles: tuple[str, ...]
    independent_evidence_count: int = 1
    personalization_adjustment: PersonalizationAdjustment | None = None


def delta_kind_for(
    delta_type: str,
    *,
    additional_source_roles: Sequence[str] = (),
) -> DisplayDeltaKind:
    normalized = (delta_type or "").strip().casefold()
    if normalized in _CORRECTION_DELTAS:
        return "correction"
    if normalized in _CONFLICT_DELTAS:
        return "conflict"
    if normalized in _DETAIL_DELTAS:
        return "additional"
    if normalized in _STATE_DELTAS:
        return "state_update"
    if additional_source_roles:
        return "new_fact"
    return "new_fact"


def match_kind_for(relation_level: str, relation_reason: str) -> DisplayMatchKind:
    lowered = (relation_reason or "").casefold()
    if "(inferred/" in lowered or "inferred/" in lowered:
        return "inferred"
    level = (relation_level or "").strip().casefold()
    if level == "direct":
        return "direct"
    if level == "adjacent":
        return "adjacent"
    return "reference"


def build_display_reason(inputs: DisplayReasonInputs) -> DisplayReason:
    """Build a versioned reason from actual ranker/projection fields only."""
    match_kind = match_kind_for(inputs.relation_level, inputs.relation_reason)
    delta_kind = delta_kind_for(
        inputs.delta_type,
        additional_source_roles=inputs.additional_source_roles,
    )
    codes: list[str] = []
    fragments: list[str] = []

    priority_code = _priority_code(inputs.priority_rule)
    delta_code = _delta_code(delta_kind)
    distinctive_delta = delta_kind in {"additional", "state_update", "correction", "conflict"}
    relation_code, relation_text = _relation_code_and_text(
        match_kind,
        inputs.matched_topics,
        inputs.matched_repository_names,
    )

    if priority_code is not None:
        codes.append(priority_code)
        fragments.append(_priority_text(priority_code))
        if distinctive_delta and delta_code is not None and delta_code not in codes:
            codes.append(delta_code)
        codes.append(relation_code)
    elif distinctive_delta and delta_code is not None:
        codes.append(delta_code)
        fragments.append(_delta_text(delta_code))
        codes.append(relation_code)
        fragments.append(relation_text)
    else:
        codes.append(relation_code)
        fragments.append(relation_text)
        if delta_code is not None and delta_code not in codes:
            codes.append(delta_code)

    if distinctive_delta and delta_code is not None and delta_code not in codes:
        codes.append(delta_code)

    if inputs.knownness_state == STATE_UNKNOWN:
        codes.append("novelty.possibly_unread")
        if priority_code is None:
            fragments.append("まだ見ていない可能性が高い")
    elif inputs.knownness_state == STATE_PROBABLY_KNOWN or inputs.knownness_confidence in {
        "none",
        "low",
    }:
        codes.append("novelty.uncertain_knownness")
        if priority_code is None:
            fragments.append("既知かどうかは確定していないため再表示しています")

    if inputs.redundancy_penalty > 0:
        codes.append("redundancy.topic_occupancy")
        fragments.append("同じ話題が多いため順位を下げています")

    for role in inputs.additional_source_roles:
        code = f"provenance.{role}"
        if code in codes:
            continue
        codes.append(code)
        fragments.append(_provenance_text(role))

    personalization_code, personalization_text = _personalization_code_and_text(
        inputs.personalization_adjustment
    )
    if personalization_code is not None and personalization_text:
        codes.append(personalization_code)
        fragments.append(personalization_text)

    if not fragments:
        fragments.append("追跡中の情報源に新しい事実があります")
    primary = codes[0] if codes else "delta.new_fact"
    text = "。".join(dict.fromkeys(fragment for fragment in fragments if fragment))
    if text and not text.endswith("。"):
        text = f"{text}。"
    return DisplayReason(
        policy_version=DISPLAY_REASON_POLICY_VERSION,
        ranking_policy_version=inputs.ranking_policy_version or RANKING_POLICY_VERSION,
        primary_code=primary,
        text=text,
        codes=codes,
        match_kind=match_kind,
        delta_kind=delta_kind,
        independent_evidence_count=max(1, inputs.independent_evidence_count),
    )


def reason_inconsistencies(reason: DisplayReason, inputs: DisplayReasonInputs) -> list[str]:
    """Return empty when the explanation is grounded in the same ranker inputs."""
    problems: list[str] = []
    expected = build_display_reason(inputs)
    if reason.primary_code != expected.primary_code:
        problems.append("primary_code does not match ranker-derived reason")
    if reason.delta_kind != expected.delta_kind:
        problems.append("delta_kind does not match the live delta type")
    if reason.match_kind != expected.match_kind:
        problems.append("match_kind does not match the live relation signal")
    if reason.ranking_policy_version != inputs.ranking_policy_version:
        problems.append("ranking_policy_version is not the live ranker version")
    if "priority.correction" in reason.codes and inputs.priority_rule != "correction":
        problems.append("correction text is not backed by the ranker priority rule")
    if (
        "priority.unresolved_conflict" in reason.codes
        and inputs.priority_rule != "unresolved_conflict"
    ):
        problems.append("conflict text is not backed by the ranker priority rule")
    if "priority.critical_security" in reason.codes and inputs.priority_rule != "critical_security":
        problems.append("security text is not backed by the ranker priority rule")
    if "redundancy.topic_occupancy" in reason.codes and inputs.redundancy_penalty <= 0:
        problems.append("redundancy text is not backed by a live redundancy penalty")
    adjustment = inputs.personalization_adjustment
    personalization_codes = [
        code for code in reason.codes if code.startswith("personalization.feedback_")
    ]
    if adjustment is not None:
        expected_code = _PERSONALIZATION_CODES[adjustment]
        if expected_code not in reason.codes:
            problems.append("personalization code is not backed by the live overlay")
        if _PERSONALIZATION_TEXT[adjustment] not in reason.text:
            problems.append("personalization text is not backed by the live overlay")
        unexpected = [code for code in personalization_codes if code != expected_code]
        if unexpected:
            problems.append("personalization text is not backed by the live overlay")
    elif personalization_codes:
        problems.append("personalization text is not backed by a live overlay")
    allowed_names = {name.casefold() for name in inputs.matched_topics}
    allowed_names.update(name.casefold() for name in inputs.matched_repository_names)
    for token in _named_entities(reason.text):
        if token.casefold() not in allowed_names:
            problems.append(f"explanation mentions {token!r} which is not a live match")
    for phrase in _ASSERTED_KNOWNNESS:
        if phrase in reason.text:
            problems.append("knownness is asserted instead of hedged")
    return problems


def _priority_code(rule: str | None) -> str | None:
    if rule == "correction":
        return "priority.correction"
    if rule == "unresolved_conflict":
        return "priority.unresolved_conflict"
    if rule == "critical_security":
        return "priority.critical_security"
    if rule == "critical_incident":
        return "priority.critical_incident"
    return None


def _priority_text(code: str) -> str:
    return {
        "priority.correction": "以前の情報を訂正しています",
        "priority.unresolved_conflict": "一次情報源の間で未解決の矛盾があります",
        "priority.critical_security": "重大な脆弱性の可能性があります",
        "priority.critical_incident": "重大な障害の可能性があります",
    }[code]


def _delta_code(kind: DisplayDeltaKind) -> str | None:
    return {
        "correction": "delta.correction",
        "conflict": "delta.conflict",
        "additional": "delta.additional",
        "state_update": "delta.state_update",
        "new_fact": "delta.new_fact",
        "duplicate": "delta.duplicate",
    }.get(kind)


def _delta_text(code: str) -> str:
    return {
        "delta.correction": "以前の情報を訂正しています",
        "delta.conflict": "一次情報源の間で未解決の矛盾があります",
        "delta.additional": "同じ話の新しい詳細です",
        "delta.state_update": "数値・版・状態が更新されています",
        "delta.new_fact": "追跡中の情報源に新しい事実があります",
        "delta.duplicate": "同じ内容のため重複カードは増やしていません",
    }.get(code, "")


def _relation_code_and_text(
    match_kind: DisplayMatchKind,
    topics: Sequence[str],
    repositories: Sequence[str],
) -> tuple[str, str]:
    topic = next((item for item in topics if item.strip()), "")
    repo = next((item for item in repositories if item.strip()), "")
    if match_kind == "direct" and repo:
        return "relation.direct_repository", f"選択中の{repo}の更新"
    if match_kind == "direct" and topic:
        return "relation.direct_topic", f"フォロー中の{topic}に関連"
    if match_kind == "inferred" and topic:
        return "relation.inferred_interest", f"{topic}への推定上の関心に関連"
    if match_kind == "adjacent" and topic:
        return "relation.adjacent_topic", f"フォロー中の{topic}の周辺に関連"
    if match_kind == "direct":
        return "relation.direct_topic", "直接フォロー中の対象に関連"
    if match_kind == "inferred":
        return "relation.inferred_interest", "推定上の関心に関連"
    if match_kind == "adjacent":
        return "relation.adjacent_topic", "フォロー中トピックの周辺に関連"
    return "relation.reference", "参考情報として表示しています"


def personalization_adjustment_from_reasons(
    importance_reason: str,
    relation_reason: str,
    *,
    version: str,
) -> PersonalizationAdjustment | None:
    """Map live overlay reason suffixes onto the user-facing personalization axis."""
    if version and version in (importance_reason or ""):
        return "boost_importance"
    if version and version in (relation_reason or ""):
        return "demote_relation"
    return None


def _personalization_code_and_text(
    adjustment: PersonalizationAdjustment | None,
) -> tuple[str | None, str]:
    if adjustment is None:
        return None, ""
    return _PERSONALIZATION_CODES[adjustment], _PERSONALIZATION_TEXT[adjustment]


def _provenance_text(role: str) -> str:
    return {
        "syndication": "同一系統の再配信は独立した証拠として数えていません",
        "independent_confirmation": "別の一次情報源が同じ事実を裏付けています",
        "restatement": "同じ内容の別ソースは出典にまとめました",
    }.get(role, "")


def _named_entities(text: str) -> tuple[str, ...]:
    """Extract follow/repo names copied into the sentence.

    Only tokens that this module itself interpolates are checked, so a later
    wording change cannot invent unconstrained proper nouns.
    """
    names: list[str] = []
    for prefix, suffix in (
        ("選択中の", "の更新"),
        ("フォロー中の", "に関連"),
        ("フォロー中の", "の周辺に関連"),
        ("", "への推定上の関心に関連"),
    ):
        if prefix and prefix in text and suffix in text:
            start = text.index(prefix) + len(prefix)
            end = text.index(suffix, start)
            token = text[start:end].strip()
            if token:
                names.append(token)
        elif not prefix and suffix in text:
            end = text.index(suffix)
            token = text[:end].split("。")[-1].strip()
            if token:
                names.append(token)
    return tuple(names)
