from app.services.display_reason import (
    DISPLAY_REASON_POLICY_VERSION,
    DisplayReasonInputs,
    build_display_reason,
    reason_inconsistencies,
)
from app.services.multiobjective_ranker import RANKING_POLICY_VERSION


def _inputs(**overrides: object) -> DisplayReasonInputs:
    payload = dict(
        ranking_policy_version=RANKING_POLICY_VERSION,
        priority_rule=None,
        redundancy_penalty=0.0,
        relation_level="adjacent",
        relation_reason=(
            "Matches Rust (explicit/direct, interest:rust, score=0.900). version=relation-features-v02"
        ),
        matched_topics=("Rust",),
        matched_repository_names=(),
        importance_level="medium",
        delta_type="new_fact",
        knownness_state="unknown",
        knownness_confidence="none",
        additional_source_roles=(),
        independent_evidence_count=1,
    )
    payload.update(overrides)
    return DisplayReasonInputs(**payload)  # type: ignore[arg-type]


def test_reason_uses_live_ranker_priority_and_does_not_invent_topics() -> None:
    correction = build_display_reason(_inputs(priority_rule="correction", delta_type="correction"))
    assert correction.policy_version == DISPLAY_REASON_POLICY_VERSION
    assert correction.ranking_policy_version == RANKING_POLICY_VERSION
    assert correction.primary_code == "priority.correction"
    assert correction.delta_kind == "correction"
    assert "訂正" in correction.text
    assert (
        reason_inconsistencies(correction, _inputs(priority_rule="correction", delta_type="correction")) == []
    )

    conflict = build_display_reason(
        _inputs(priority_rule="unresolved_conflict", delta_type="unresolved_contradiction")
    )
    assert conflict.primary_code == "priority.unresolved_conflict"
    assert conflict.delta_kind == "conflict"

    security = build_display_reason(_inputs(priority_rule="critical_security"))
    assert security.primary_code == "priority.critical_security"
    assert "脆弱性" in security.text

    fabricated = correction.model_copy(update={"text": f"{correction.text}フォロー中のGoに関連。"})
    problems = reason_inconsistencies(
        fabricated,
        _inputs(priority_rule="correction", delta_type="correction"),
    )
    assert any("Go" in item for item in problems)


def test_direct_adjacent_and_inferred_are_distinguished() -> None:
    direct = build_display_reason(
        _inputs(
            relation_level="direct",
            matched_repository_names=("acme/widget",),
            relation_reason="selected repository",
        )
    )
    assert direct.match_kind == "direct"
    assert direct.primary_code == "relation.direct_repository"
    assert "acme/widget" in direct.text

    adjacent = build_display_reason(_inputs())
    assert adjacent.match_kind == "adjacent"
    assert adjacent.primary_code == "relation.adjacent_topic"
    assert "Rust" in adjacent.text

    inferred = build_display_reason(
        _inputs(
            relation_level="adjacent",
            relation_reason="Matches Rust (inferred/direct, inferred:rust, score=0.400). version=v",
        )
    )
    assert inferred.match_kind == "inferred"
    assert inferred.primary_code == "relation.inferred_interest"
    assert "推定" in inferred.text


def test_knownness_is_hedged_and_redundancy_requires_live_penalty() -> None:
    unread = build_display_reason(_inputs())
    assert "novelty.possibly_unread" in unread.codes
    assert "可能性" in unread.text
    assert "知らない" not in unread.text
    assert "知っている" not in unread.text

    demoted = build_display_reason(_inputs(redundancy_penalty=0.42))
    assert "redundancy.topic_occupancy" in demoted.codes
    assert "順位を下げ" in demoted.text
    invented = unread.model_copy(
        update={
            "codes": [*unread.codes, "redundancy.topic_occupancy"],
            "text": f"{unread.text}順位を下げています。",
        }
    )
    assert reason_inconsistencies(invented, _inputs())


def test_additional_and_duplicate_provenance_codes() -> None:
    additional = build_display_reason(_inputs(delta_type="detail"))
    assert additional.delta_kind == "additional"
    assert "delta.additional" in additional.codes
    assert "新しい詳細" in additional.text

    restated = build_display_reason(_inputs(additional_source_roles=("restatement",)))
    assert restated.delta_kind == "new_fact"
    assert "provenance.restatement" in restated.codes
    assert restated.independent_evidence_count == 1

    syndicated = build_display_reason(
        _inputs(additional_source_roles=("syndication",), independent_evidence_count=1)
    )
    assert "provenance.syndication" in syndicated.codes
    assert syndicated.independent_evidence_count == 1


def test_feedback_overlay_is_explained_without_version_codes() -> None:
    boosted = build_display_reason(
        _inputs(
            relation_level="direct",
            relation_reason="selected topic",
            personalization_adjustment="boost_importance",
        )
    )
    assert "personalization.feedback_boost" in boosted.codes
    assert "重要マーク" in boosted.text
    assert "ranking-feedback" not in boosted.text
    assert "personalization.feedback_boost" not in boosted.text
    assert (
        reason_inconsistencies(
            boosted,
            _inputs(
                relation_level="direct",
                relation_reason="selected topic",
                personalization_adjustment="boost_importance",
            ),
        )
        == []
    )

    demoted = build_display_reason(
        _inputs(
            relation_level="direct",
            relation_reason="selected topic",
            personalization_adjustment="demote_relation",
        )
    )
    assert "personalization.feedback_demote" in demoted.codes
    assert "無関係マーク" in demoted.text
    assert (
        reason_inconsistencies(
            demoted,
            _inputs(
                relation_level="direct",
                relation_reason="selected topic",
                personalization_adjustment="demote_relation",
            ),
        )
        == []
    )

    invented = boosted.model_copy(
        update={"codes": [*boosted.codes, "personalization.feedback_demote"]}
    )
    problems = reason_inconsistencies(
        invented,
        _inputs(
            relation_level="direct",
            relation_reason="selected topic",
            personalization_adjustment="boost_importance",
        ),
    )
    assert problems

    unbacked = build_display_reason(
        _inputs(relation_level="direct", relation_reason="selected topic")
    )
    assert "personalization.feedback_boost" not in unbacked.codes
    assert "重要マーク" not in unbacked.text
    leaked = unbacked.model_copy(
        update={
            "codes": [*unbacked.codes, "personalization.feedback_boost"],
            "text": f"{unbacked.text}これまでの重要マークに合わせて並びを調整しています。",
        }
    )
    assert reason_inconsistencies(
        leaked, _inputs(relation_level="direct", relation_reason="selected topic")
    )


def test_preference_overlay_is_explained_when_discrete_feedback_did_not_apply() -> None:
    preferred = build_display_reason(
        _inputs(
            relation_level="direct",
            relation_reason="selected topic",
            preference_overlay_applied=True,
        )
    )
    assert "personalization.preference_overlay" in preferred.codes
    assert "評価傾向" in preferred.text
    assert "offline-preference" not in preferred.text
    assert "personalization.preference_overlay" not in preferred.text
    assert (
        reason_inconsistencies(
            preferred,
            _inputs(
                relation_level="direct",
                relation_reason="selected topic",
                preference_overlay_applied=True,
            ),
        )
        == []
    )

    discrete_wins = build_display_reason(
        _inputs(
            relation_level="direct",
            relation_reason="selected topic",
            personalization_adjustment="boost_importance",
            preference_overlay_applied=True,
        )
    )
    assert "personalization.feedback_boost" in discrete_wins.codes
    assert "personalization.preference_overlay" not in discrete_wins.codes
    assert "評価傾向" not in discrete_wins.text
    assert (
        reason_inconsistencies(
            discrete_wins,
            _inputs(
                relation_level="direct",
                relation_reason="selected topic",
                personalization_adjustment="boost_importance",
                preference_overlay_applied=True,
            ),
        )
        == []
    )
