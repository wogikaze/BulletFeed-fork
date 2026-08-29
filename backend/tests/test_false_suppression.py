from pathlib import Path

import pytest

from app.evaluation.false_suppression import (
    DATASET_VERSION,
    REQUIRED_FAMILIES,
    evaluate_policy,
    hide_non_unknown_prediction,
    load_false_suppression_gold,
    policy_prediction,
    require_false_suppression_gate,
    require_no_repetition_false_suppression_tradeoff,
)
from app.services.false_suppression import (
    MIN_HIDE_CONFIDENCE,
    POLICY_VERSION,
    decide_suppression,
    may_hide,
    presentation_for_candidate,
    reconstruct_why_hidden,
    record_suppression,
)
from app.services.knowledge_evidence import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    STATE_KNOWN,
    STATE_PROBABLY_KNOWN,
    STATE_UNKNOWN,
)
from app.services.knowledge_identity import (
    KNOWLEDGE_IDENTITY_VERSION,
    KnowledgeIdentityDecision,
    compare_knowledge_identity,
)

_GOLD = Path(__file__).parent / "gold" / "false_suppression_v01.json"


def _cases():
    return load_false_suppression_gold(_GOLD)


def test_uncertain_never_may_hide() -> None:
    uncertain_states = (
        (STATE_UNKNOWN, CONFIDENCE_NONE),
        (STATE_UNKNOWN, CONFIDENCE_LOW),
        (STATE_PROBABLY_KNOWN, CONFIDENCE_MEDIUM),
        (STATE_KNOWN, CONFIDENCE_MEDIUM),
        (STATE_KNOWN, CONFIDENCE_LOW),
    )
    for state, confidence in uncertain_states:
        assert may_hide(state=state, confidence=confidence) is False
        assert presentation_for_candidate(state=state, confidence=confidence) != "hide"

    assert (
        may_hide(
            state=STATE_KNOWN,
            confidence=CONFIDENCE_HIGH,
            identity_label="uncertain",
            identity_confidence="low",
            equivalence_label="uncertain",
        )
        is False
    )
    assert (
        may_hide(
            state=STATE_KNOWN,
            confidence=CONFIDENCE_HIGH,
            identity_label="same_target",
            identity_confidence="medium",
        )
        is False
    )
    assert (
        may_hide(
            state=STATE_PROBABLY_KNOWN,
            confidence=CONFIDENCE_MEDIUM,
            stale_exposure=True,
        )
        is False
    )
    for case in _cases():
        if case.family in {
            "uncertain_paraphrase",
            "stale_exposure",
            "low_confidence_known",
            "high_importance_unknown",
        }:
            decision = decide_suppression(
                knowledge_state=case.knowledge_state,
                knowledge_confidence=case.knowledge_confidence,
                identity_label=case.identity_label,
                identity_confidence=case.identity_confidence,
                equivalence_label=case.equivalence_label,
                revision_class=case.revision_class,
                importance_level=case.importance_level,
                stale_exposure=case.stale_exposure,
            )
            assert decision.may_hide is False, case.case_id
            assert decision.action != "hide", case.case_id


def test_critical_unknown_always_surfaces() -> None:
    for confidence in (CONFIDENCE_NONE, CONFIDENCE_LOW, CONFIDENCE_MEDIUM):
        decision = decide_suppression(
            knowledge_state=STATE_UNKNOWN,
            knowledge_confidence=confidence,
            importance_level="critical",
        )
        assert decision.action == "show"
        assert decision.may_hide is False
        assert may_hide(
            state=STATE_UNKNOWN,
            confidence=confidence,
            importance_level="critical",
        ) is False

    delivered_only = decide_suppression(
        knowledge_state=STATE_UNKNOWN,
        knowledge_confidence=CONFIDENCE_LOW,
        importance_level="high",
        stale_exposure=False,
    )
    assert delivered_only.action == "show"

    gold = next(case for case in _cases() if case.family == "high_importance_unknown")
    assert policy_prediction(gold) == "show"


def test_false_suppression_metric_is_separate_from_repetition() -> None:
    cases = _cases()
    conservative = evaluate_policy(cases, policy_prediction)
    aggressive = evaluate_policy(cases, hide_non_unknown_prediction)

    assert conservative.false_suppression_rate != conservative.repetition_rate or (
        conservative.unknown_count != conservative.known_duplicate_count
    )
    assert conservative.dataset_version == DATASET_VERSION
    assert conservative.false_suppression_rate == 0.0
    assert conservative.unknown_but_hidden_count == 0
    assert conservative.repetition_rate > 0.0
    assert conservative.repeated_ids == ("probably-known-restatement",)

    assert aggressive.repetition_rate < conservative.repetition_rate
    assert aggressive.false_suppression_rate > conservative.false_suppression_rate
    assert aggressive.unknown_but_hidden_count > 0
    assert "uncertain-paraphrase" in aggressive.hidden_ids
    assert "critical-unknown" not in aggressive.hidden_ids


def test_gold_covers_required_families_and_policy_version() -> None:
    cases = _cases()
    families = {case.family for case in cases}
    assert set(REQUIRED_FAMILIES) <= families
    assert {case.case_id for case in cases} >= {
        "uncertain-paraphrase",
        "partial-detail",
        "stale-exposure",
        "correction-after-known",
        "conflicting-source",
        "critical-unknown",
    }
    for case in cases:
        decision = decide_suppression(
            knowledge_state=case.knowledge_state,
            knowledge_confidence=case.knowledge_confidence,
            identity_label=case.identity_label,
            identity_confidence=case.identity_confidence,
            equivalence_label=case.equivalence_label,
            revision_class=case.revision_class,
            importance_level=case.importance_level,
            stale_exposure=case.stale_exposure,
        )
        assert decision.version == POLICY_VERSION
        assert decision.reason
        assert decision.action in case.allowed_actions, case.case_id
        assert decision.action not in case.forbidden_actions, case.case_id


def test_suppressed_candidate_records_reason_and_version() -> None:
    decision = decide_suppression(
        knowledge_state=STATE_KNOWN,
        knowledge_confidence=CONFIDENCE_HIGH,
        identity_label="same_target",
        identity_confidence=CONFIDENCE_HIGH,
        equivalence_label="equivalent",
        revision_class="NON_NOVEL",
    )
    assert decision.action == "hide"
    assert decision.may_hide is True
    assert decision.version == POLICY_VERSION
    assert decision.reason
    record = record_suppression("candidate-known-restatement", decision)
    assert record["candidate_id"] == "candidate-known-restatement"
    assert record["reason"] == decision.reason
    assert record["version"] == POLICY_VERSION
    assert record["action"] == "hide"


def test_debug_can_reconstruct_why_hidden() -> None:
    hidden = decide_suppression(
        knowledge_state=STATE_KNOWN,
        knowledge_confidence=CONFIDENCE_HIGH,
        identity_label="same_target",
        identity_confidence=CONFIDENCE_HIGH,
        equivalence_label="equivalent",
    )
    shown = decide_suppression(
        knowledge_state=STATE_KNOWN,
        knowledge_confidence=CONFIDENCE_HIGH,
        identity_label="uncertain",
        identity_confidence="low",
        equivalence_label="uncertain",
    )
    hidden_text = reconstruct_why_hidden(hidden)
    shown_text = reconstruct_why_hidden(shown)
    assert POLICY_VERSION in hidden_text
    assert "action=hide" in hidden_text
    assert "may_hide=true" in hidden_text
    assert hidden.reason in hidden_text
    assert "action=show" in shown_text
    assert "uncertain" in shown_text
    assert shown.reason in shown_text
    replayed = decide_suppression(
        knowledge_state=hidden.knowledge_state,
        knowledge_confidence=hidden.knowledge_confidence,
        identity_label=hidden.identity_label,
        identity_confidence=hidden.identity_confidence,
        equivalence_label=hidden.equivalence_label,
    )
    assert replayed == hidden


def test_high_importance_correction_and_conflict_cross_suppression() -> None:
    correction = decide_suppression(
        knowledge_state=STATE_KNOWN,
        knowledge_confidence=CONFIDENCE_HIGH,
        identity_label="same_target",
        identity_confidence=CONFIDENCE_HIGH,
        revision_class="CORRECTION",
        importance_level="critical",
    )
    conflict = decide_suppression(
        knowledge_state=STATE_KNOWN,
        knowledge_confidence=CONFIDENCE_HIGH,
        identity_label="same_target",
        identity_confidence=CONFIDENCE_HIGH,
        revision_class="UNRESOLVED_CONTRADICTION",
        importance_level="high",
    )
    assert correction.action == "show"
    assert conflict.action == "show"
    assert correction.may_hide is False
    assert conflict.may_hide is False


def test_partial_detail_and_stale_exposure_never_hide() -> None:
    partial = decide_suppression(
        knowledge_state=STATE_KNOWN,
        knowledge_confidence=CONFIDENCE_HIGH,
        identity_label="different_target",
        equivalence_label="not_equivalent",
        revision_class="DETAIL",
    )
    stale = decide_suppression(
        knowledge_state=STATE_PROBABLY_KNOWN,
        knowledge_confidence=CONFIDENCE_MEDIUM,
        identity_label="same_target",
        identity_confidence=CONFIDENCE_MEDIUM,
        stale_exposure=True,
    )
    assert partial.action == "show"
    assert stale.action in {"show", "demote"}
    assert partial.may_hide is False
    assert stale.may_hide is False


def test_suppression_requires_minimum_knowledge_confidence() -> None:
    assert MIN_HIDE_CONFIDENCE == CONFIDENCE_HIGH
    below = decide_suppression(
        knowledge_state=STATE_KNOWN,
        knowledge_confidence=CONFIDENCE_MEDIUM,
        identity_label="same_target",
        identity_confidence=CONFIDENCE_HIGH,
        equivalence_label="equivalent",
    )
    assert below.action != "hide"
    assert below.may_hide is False
    assert "minimum knowledge confidence" in below.reason


def test_uncertain_identity_pair_never_hides() -> None:
    decision = compare_knowledge_identity(
        "issue",
        "database latency issue",
        "issue",
        "database capacity issue",
        left_slot="status",
        right_slot="status",
    )
    assert decision.label == "uncertain"
    assert decision.version == KNOWLEDGE_IDENTITY_VERSION
    assert (
        may_hide(
            state=STATE_KNOWN,
            confidence=CONFIDENCE_HIGH,
            identity=decision,
        )
        is False
    )
    assert (
        presentation_for_candidate(
            state=STATE_KNOWN,
            confidence=CONFIDENCE_HIGH,
            identity=decision,
        )
        != "hide"
    )


def test_identity_object_same_target_can_hide() -> None:
    identity = KnowledgeIdentityDecision(
        "same_target",
        "canonical fingerprint is identical",
        "high",
        KNOWLEDGE_IDENTITY_VERSION,
        "knid_left",
        "knid_right",
        "knid_left",
    )
    assert (
        may_hide(
            state=STATE_KNOWN,
            confidence=CONFIDENCE_HIGH,
            identity=identity,
            equivalence_label="equivalent",
        )
        is True
    )


def test_release_gate_rejects_unknown_but_hidden() -> None:
    cases = _cases()
    conservative = evaluate_policy(cases, policy_prediction)
    require_false_suppression_gate(conservative)
    aggressive = evaluate_policy(cases, hide_non_unknown_prediction)
    with pytest.raises(AssertionError, match="false_suppression_rate"):
        require_false_suppression_gate(aggressive)


def test_release_regression_cannot_trade_repetition_for_false_suppression() -> None:
    cases = _cases()
    conservative = evaluate_policy(cases, policy_prediction)
    aggressive = evaluate_policy(cases, hide_non_unknown_prediction)
    require_no_repetition_false_suppression_tradeoff(conservative, conservative)
    with pytest.raises(AssertionError, match="unknown-but-hidden"):
        require_no_repetition_false_suppression_tradeoff(aggressive, conservative)
