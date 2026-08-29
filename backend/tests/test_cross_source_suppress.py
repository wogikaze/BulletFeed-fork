from pathlib import Path

from app.evaluation.cross_source_suppress import (
    DATASET_VERSION,
    REQUIRED_FAMILIES,
    evaluate_cross_source,
    load_cross_source_gold,
    project_case,
)
from app.schemas.common import Delta, Importance, Relation
from app.schemas.feed import PublicFeedItem
from app.services.cross_source_suppress import (
    GUARD_POLICY_VERSION,
    POLICY_VERSION,
    SourceCandidate,
    decide_guard,
    independent_evidence_count,
    project_candidates,
    record_projection,
    resolve_identity,
)
from app.services.false_suppression import decide_suppression
from app.services.knowledge_evidence import (
    CONFIDENCE_HIGH,
    CONFIDENCE_NONE,
    STATE_KNOWN,
    STATE_UNKNOWN,
)
from app.services.knowledge_identity import (
    KNOWLEDGE_IDENTITY_VERSION,
    compare_knowledge_identity,
    identity_may_hide,
)

_GOLD = Path(__file__).parent / "gold" / "cross_source_suppress_v01.json"


def _cases():
    return load_cross_source_gold(_GOLD)


def _candidate(**overrides: object) -> SourceCandidate:
    base = dict(
        candidate_id="c1",
        source_id="src:1",
        publisher="Acme",
        kind="statuspage",
        title="Latency",
        url="https://status.acme.test/1",
        published_at="2026-08-22T00:00:00Z",
        retrieved_at="2026-08-22T00:01:00Z",
        evidence="Investigating elevated latency.",
        value="investigating",
        detail="Investigating elevated latency.",
        slot="status",
        revision_class="NEW_FACT",
        dependence_key="incident:1",
        knowledge_state=STATE_UNKNOWN,
        knowledge_confidence=CONFIDENCE_NONE,
        importance_level="high",
    )
    base.update(overrides)
    return SourceCandidate(**base)  # type: ignore[arg-type]


def test_gold_covers_required_families_and_policy_version() -> None:
    cases = _cases()
    families = {case.family for case in cases}
    assert set(REQUIRED_FAMILIES) <= families
    assert {case.case_id for case in cases} >= {
        "duplicate-press-release",
        "syndicated-advisory",
        "independent-confirmation",
        "later-source-adds-detail",
        "later-source-contradicts",
    }
    for case in cases:
        batch = project_case(case)
        assert batch.version == POLICY_VERSION
        assert tuple(batch.displayed_ids) == case.expected_displayed_ids, case.case_id
        assert tuple(batch.additional_source_ids) == case.expected_additional_ids, case.case_id
        assert tuple(batch.hidden_ids) == case.expected_hidden_ids, case.case_id
        if case.should_surface:
            assert batch.displayed_ids, case.case_id
        displayed_cards = [card for card in batch.cards if card.action != "hide"]
        if case.family in {
            "duplicate_press_release",
            "syndication",
            "independent_confirmation",
        }:
            assert len(displayed_cards) == 1, case.case_id
            assert (
                displayed_cards[0].independent_evidence_count
                == case.expected_independent_evidence_count
            )


def test_equivalent_facts_share_one_knowledge_target() -> None:
    decision = compare_knowledge_identity(
        "investigating",
        "Investigating elevated latency.",
        "investigating",
        "We are investigating elevated latency.",
        left_slot="status",
        right_slot="status",
    )
    assert decision.label == "same_target"
    assert decision.shared_identity_id
    assert decision.version == KNOWLEDGE_IDENTITY_VERSION
    left = _candidate(candidate_id="a")
    right = _candidate(
        candidate_id="b",
        published_at="2026-08-22T00:05:00Z",
        detail="We are investigating elevated latency.",
        evidence="We are investigating elevated latency.",
        revision_class="NON_NOVEL",
        dependence_key="incident:2",
    )
    assert resolve_identity(left, right).shared_identity_id == decision.shared_identity_id


def test_independent_source_strengthens_evidence_without_duplicate_card() -> None:
    case = next(item for item in _cases() if item.family == "independent_confirmation")
    batch = project_case(case)
    assert batch.displayed_ids == ("vendor-status",)
    assert batch.additional_source_ids == ("json-confirm",)
    card = batch.cards[0]
    assert card.independent_evidence_count == 2
    assert card.additional_sources[0].role == "independent_confirmation"
    assert card.provenance()[0].publisher == "Status Mirror"


def test_syndication_does_not_inflate_independent_evidence() -> None:
    case = next(item for item in _cases() if item.family == "syndication")
    batch = project_case(case)
    card = next(item for item in batch.cards if item.action != "hide")
    assert card.independent_evidence_count == 1
    assert card.additional_sources[0].role == "syndication"
    assert independent_evidence_count(case.candidates) == 1


def test_added_detail_and_contradiction_still_surface() -> None:
    detail = next(item for item in _cases() if item.family == "added_detail")
    conflict = next(item for item in _cases() if item.family == "contradiction")
    detail_batch = project_case(detail)
    conflict_batch = project_case(conflict)
    assert "release-detail" in detail_batch.displayed_ids
    assert "release-detail" not in detail_batch.additional_source_ids
    assert "status-conflict" in conflict_batch.displayed_ids
    assert "status-conflict" not in conflict_batch.hidden_ids


def test_provenance_stays_on_canonical_card() -> None:
    case = next(item for item in _cases() if item.family == "duplicate_press_release")
    batch = project_case(case)
    card = next(item for item in batch.cards if item.displayed_id == "press-original")
    sources = card.provenance()
    assert len(sources) == 1
    assert sources[0].publisher == "News Wire"
    assert sources[0].url == "https://news.example/acme-latency"
    assert sources[0].evidence
    records = record_projection(batch)
    assert {row["candidate_id"] for row in records} == {"press-original", "press-reprint"}
    reprint = next(row for row in records if row["candidate_id"] == "press-reprint")
    assert reprint["role"] == "additional_source"
    assert reprint["guard_version"] == GUARD_POLICY_VERSION


def test_uncertain_identity_does_not_hide() -> None:
    case = next(item for item in _cases() if item.case_id == "uncertain-identity-not-hidden")
    identity = resolve_identity(case.candidates[0], case.candidates[1])
    assert identity.label == "uncertain"
    assert identity_may_hide(identity) is False
    batch = project_case(case)
    assert "capacity-issue" in batch.displayed_ids
    assert "capacity-issue" not in batch.hidden_ids
    assert "capacity-issue" not in batch.additional_source_ids


def test_dedup_runs_after_hide_guard_and_does_not_invert() -> None:
    unknown_restatement = _candidate(
        candidate_id="later",
        published_at="2026-08-22T00:05:00Z",
        detail="We are investigating elevated latency.",
        evidence="We are investigating elevated latency.",
        revision_class="NON_NOVEL",
        dependence_key="incident:later",
        knowledge_state=STATE_UNKNOWN,
        knowledge_confidence=CONFIDENCE_NONE,
    )
    first = _candidate(candidate_id="first")
    guard = decide_guard(
        unknown_restatement,
        identity=resolve_identity(first, unknown_restatement),
        revision_class="NON_NOVEL",
        equivalence_label="equivalent",
    )
    assert guard.version == GUARD_POLICY_VERSION
    assert guard.may_hide is False
    assert guard.action != "hide"
    batch = project_candidates((first, unknown_restatement))
    assert "later" not in batch.hidden_ids
    assert "first" in batch.displayed_ids
    assert "later" in batch.additional_source_ids


def test_aggressive_same_target_hide_would_invert_guard() -> None:
    """A same-target→hide policy would bury unknowns. This policy must not."""
    first = _candidate(candidate_id="first")
    later = _candidate(
        candidate_id="later",
        published_at="2026-08-22T00:05:00Z",
        detail="We are investigating elevated latency.",
        evidence="We are investigating elevated latency.",
        revision_class="NON_NOVEL",
        dependence_key="incident:later",
    )
    identity = resolve_identity(first, later)
    assert identity.label == "same_target"
    aggressive_hide = identity.label == "same_target"
    guard = decide_suppression(
        knowledge_state=STATE_UNKNOWN,
        knowledge_confidence=CONFIDENCE_NONE,
        identity=identity,
        revision_class="NON_NOVEL",
        importance_level="high",
    )
    assert aggressive_hide is True
    assert guard.may_hide is False
    batch = project_candidates((first, later))
    assert batch.displayed_ids
    assert "later" not in batch.hidden_ids


def test_known_restatement_hides_only_after_guard_allows() -> None:
    case = next(item for item in _cases() if item.family == "known_restatement")
    later = case.candidates[1]
    identity = resolve_identity(case.candidates[0], later)
    guard = decide_guard(
        later,
        identity=identity,
        revision_class="NON_NOVEL",
        equivalence_label="equivalent",
    )
    assert guard.may_hide is True
    assert later.knowledge_state == STATE_KNOWN
    assert later.knowledge_confidence == CONFIDENCE_HIGH
    batch = project_case(case)
    assert batch.displayed_ids == ()
    assert "known-reprint" in batch.hidden_ids


def test_api_additional_sources_do_not_require_duplicate_cards() -> None:
    case = next(item for item in _cases() if item.family == "independent_confirmation")
    batch = project_case(case)
    card = batch.cards[0]
    item = PublicFeedItem(
        id="fi_canonical",
        event_id="evt",
        delta=Delta(
            id="d1",
            type="new_fact",
            summary="latency",
            before="",
            after="investigating",
            occurred_at="2026-08-22T00:00:00Z",
        ),
        title="API latency",
        importance=Importance(level="medium", reason="status", confidence="high"),
        relation=Relation(
            level="direct",
            reason="followed",
            matched_topics=[],
            matched_repositories=[],
        ),
        status="unread",
        following=True,
        updated_at="2026-08-22T00:00:00Z",
        delivery_id="dlv_1",
        sources=[],
        additional_sources=list(card.provenance()),
    )
    payload = item.model_dump(by_alias=True)
    assert "additionalSources" in payload
    assert len(payload["additionalSources"]) == 1
    assert payload["additionalSources"][0]["publisher"] == "Status Mirror"


def test_evaluation_rejects_unknown_but_hidden() -> None:
    cases = _cases()
    report = evaluate_cross_source(cases)
    assert report.dataset_version == DATASET_VERSION
    assert report.policy_version == POLICY_VERSION
    assert report.false_suppression_rate == 0.0
    assert report.unknown_but_hidden_count == 0
    assert report.duplicate_card_rate == 0.0
