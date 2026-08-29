from __future__ import annotations

from pathlib import Path

from app.evaluation.delta_adversarial_gold import load_delta_adversarial_gold
from app.services.claim_slots import (
    apply_typed_slot_evidence,
    compare_typed_slots,
    extract_claim_slots,
    normalize_comparator,
    normalize_numeric_value,
    normalize_unit,
    normalize_version,
    typed_slots_as_revision_evidence,
)
from app.services.semantic_delta import ClaimSnapshot, judge_revision

_GOLD = Path(__file__).parent / "gold" / "delta_adversarial" / "v01"


def _extract_pair(prior_value: str, prior_detail: str, candidate_value: str, candidate_detail: str, **kwargs):
    prior_valid = kwargs.get("prior_valid_at", "2026-08-01T00:00:00Z")
    candidate_valid = kwargs.get("candidate_valid_at", "2026-08-02T00:00:00Z")
    prior = extract_claim_slots(
        prior_detail,
        value_text=prior_value,
        detail_text=prior_detail,
        valid_at=prior_valid,
        structured=kwargs.get("prior_structured"),
        entity=kwargs.get("entity"),
    )
    candidate = extract_claim_slots(
        candidate_detail,
        value_text=candidate_value,
        detail_text=candidate_detail,
        valid_at=candidate_valid,
        structured=kwargs.get("candidate_structured"),
        entity=kwargs.get("entity"),
    )
    return prior, candidate


def _gold_extract(case):
    prior = extract_claim_slots(
        case.prior.detail,
        value_text=case.prior.value,
        detail_text=case.prior.detail,
        valid_at=case.prior.valid_at,
    )
    candidate = extract_claim_slots(
        case.candidate.detail,
        value_text=case.candidate.value,
        detail_text=case.candidate.detail,
        valid_at=case.candidate.valid_at,
    )
    return prior, candidate


def test_extraction_never_replaces_raw_evidence():
    raw = "Upload limit increased to 1000 MB."
    result = extract_claim_slots(raw, value_text="limit 1000 mb", detail_text=raw)

    assert result.evidence_text == raw
    assert result.evidence_text is raw
    assert result.slots
    assert result.slots[0].raw_span
    assert all(slot.value != raw for slot in result.slots)


def test_confident_extraction_exposes_entity_slot_value_units_and_valid_at():
    result = extract_claim_slots(
        "Upload limit increased to 1,000 MB.",
        value_text="limit 1000 mb",
        detail_text="Upload limit increased to 1,000 MB.",
        entity="Actions",
        valid_at="2026-08-01T00:00:00Z",
    )
    limit = result.slots_named("limit")[0]

    assert result.abstained is False
    assert limit.entity == "Actions"
    assert limit.slot == "limit"
    assert limit.value == "1000"
    assert limit.unit == "MB"
    assert "upload" in limit.qualifiers
    assert limit.valid_at == "2026-08-01T00:00:00Z"
    assert limit.confidence == "high"


def test_unknown_or_ambiguous_slot_abstains():
    result = extract_claim_slots(
        "Service capacity policy is active for standard users.",
        value_text="capacity policy",
        detail_text="Service capacity policy changes for selected users.",
    )

    assert result.evidence_text == "Service capacity policy is active for standard users."
    assert result.slots == ()
    assert result.abstained is True
    assert compare_typed_slots(result, result) is None
    assert typed_slots_as_revision_evidence(result, result) is None
    assert apply_typed_slot_evidence(typed=None) is None


def test_structured_fields_are_authoritative_over_prose():
    result = extract_claim_slots(
        "Node.js 20.19.0 is the current LTS release.",
        value_text="current lts",
        detail_text="Node.js 20.19.0 is the current LTS release.",
        structured={"entity": "Node.js", "version": "20.19.1", "severity": "high"},
        valid_at="2026-05-15T00:00:00Z",
    )
    version = result.slots_named("version")[0]
    severity = result.slots_named("severity")[0]

    assert result.evidence_text == "Node.js 20.19.0 is the current LTS release."
    assert version.value == "20.19.1"
    assert version.origin == "structured"
    assert version.entity == "Node.js"
    assert severity.value == "high"
    assert severity.origin == "structured"


def test_numeric_unit_and_version_normalization_is_deterministic():
    left = extract_claim_slots(
        "Limit increased to 1,000 requests per minute.",
        value_text="active",
        detail_text="Limit increased to 1,000 requests per minute.",
    )
    right = extract_claim_slots(
        "The per-minute request cap is now one thousand.",
        value_text="active",
        detail_text="The per-minute request cap is now one thousand.",
    )
    delta = compare_typed_slots(left, right)

    assert normalize_numeric_value("1,000") == normalize_numeric_value("one thousand") == "1000"
    assert normalize_unit("requests per minute") == normalize_unit("requests/min") == "requests/min"
    assert normalize_version("v20.19.1") == normalize_version("20.19.1") == "20.19.1"
    assert left.slots_named("limit")[0].identity == right.slots_named("limit")[0].identity
    assert delta is not None
    assert delta.kind == "same_slot_equivalent"
    assert typed_slots_as_revision_evidence(left, right) is None


def test_comparator_direction_is_preserved_and_never_flipped():
    prior, candidate = _extract_pair(
        "minimum >= 3.10",
        "Python >= 3.10 is required.",
        "maximum <= 3.10",
        "Python <= 3.10 is required.",
    )
    prior_range = prior.slots_named("affected_version_range")[0]
    candidate_range = candidate.slots_named("affected_version_range")[0]
    delta = compare_typed_slots(prior, candidate)

    assert prior_range.comparator == ">="
    assert candidate_range.comparator == "<="
    assert prior_range.value == candidate_range.value == "3.10"
    assert normalize_comparator("≥") == ">="
    assert normalize_comparator("≤") == "<="
    assert delta is not None
    assert delta.kind == "same_slot_value_change"
    assert ">=" in (delta.prior_value or "")
    assert "<=" in (delta.candidate_value or "")
    assert apply_typed_slot_evidence(typed=delta) == "STATE_UPDATE"


def test_revision_judge_can_consume_typed_value_change_without_forcing_low_confidence():
    prior, candidate = _extract_pair(
        "limit 1000 mb",
        "Upload limit increased to 1000 MB.",
        "limit 1000 gb",
        "Upload limit increased to 1000 GB.",
    )
    typed = typed_slots_as_revision_evidence(prior, candidate)
    prose_decision = judge_revision(
        ClaimSnapshot("limit 1000 mb", "Upload limit increased to 1000 MB.", "2026-08-01T00:00:00Z"),
        ClaimSnapshot("limit 1000 gb", "Upload limit increased to 1000 GB.", "2026-08-02T00:00:00Z"),
    )

    assert typed is not None
    assert typed.kind == "same_slot_value_change"
    assert typed.confidence in {"high", "medium"}
    assert apply_typed_slot_evidence(
        typed=typed,
        prior_valid_at="2026-08-01T00:00:00Z",
        candidate_valid_at="2026-08-02T00:00:00Z",
    ) == "STATE_UPDATE"
    assert prose_decision.revision_type in {"STATE_UPDATE", "UNRESOLVED_CONTRADICTION"}
    if prose_decision.revision_type == "UNRESOLVED_CONTRADICTION":
        assert prose_decision.abstained is True

    vague_prior, vague_candidate = _extract_pair(
        "capacity policy",
        "Service capacity policy is active for standard users.",
        "capacity policy",
        "Service capacity policy changes for selected users.",
    )
    vague = typed_slots_as_revision_evidence(vague_prior, vague_candidate)
    vague_decision = judge_revision(
        ClaimSnapshot(
            "service capacity enabled",
            "Capacity policy is active for standard users",
            "2026-08-01T00:00:00Z",
        ),
        ClaimSnapshot(
            "service capacity policy",
            "Capacity policy changes for selected users",
            "2026-08-02T00:00:00Z",
        ),
    )

    assert vague is None
    assert apply_typed_slot_evidence(typed=vague) is None
    assert vague_decision.abstained is True
    assert vague_decision.confidence == "low"


def test_gold_restated_limit_is_same_slot_equivalent():
    corpus = load_delta_adversarial_gold(_GOLD)
    case = corpus.case_by_id()["dag-p-013"]
    prior, candidate = _gold_extract(case)
    delta = compare_typed_slots(prior, candidate)

    assert prior.evidence_text == case.prior.detail
    assert candidate.evidence_text == case.candidate.detail
    assert prior.slots_named("limit")[0].identity == candidate.slots_named("limit")[0].identity
    assert delta is not None
    assert delta.kind == "same_slot_equivalent"
    assert typed_slots_as_revision_evidence(prior, candidate) is None
    assert case.revision_class == "NON_NOVEL"


def test_gold_same_slot_changed_value():
    corpus = load_delta_adversarial_gold(_GOLD)
    cases = [corpus.case_by_id()[case_id] for case_id in ("dag-p-006", "dag-p-007", "dag-p-027")]

    for case in cases:
        prior, candidate = _gold_extract(case)
        delta = compare_typed_slots(prior, candidate)
        assert prior.evidence_text == case.prior.detail
        assert candidate.evidence_text == case.candidate.detail
        assert delta is not None
        assert delta.kind == "same_slot_value_change"
        assert apply_typed_slot_evidence(
            typed=delta,
            prior_valid_at=case.prior.valid_at,
            candidate_valid_at=case.candidate.valid_at,
        ) == "STATE_UPDATE"


def test_gold_different_slot_added_detail():
    corpus = load_delta_adversarial_gold(_GOLD)
    case = corpus.case_by_id()["dag-p-012"]
    prior, candidate = _gold_extract(case)
    limit_delta = compare_typed_slots(prior, candidate)

    assert prior.evidence_text == case.prior.detail
    assert "burst guidance" in candidate.evidence_text
    assert prior.slots_named("limit")[0].identity == candidate.slots_named("limit")[0].identity
    assert limit_delta is not None
    assert limit_delta.kind == "same_slot_equivalent"
    assert typed_slots_as_revision_evidence(prior, candidate) is None

    added_prior, added_candidate = _extract_pair(
        "limit 1000 requests/min",
        "API v2 rate limit is 1,000 requests per minute.",
        "limit 1000 requests/min",
        "API v2 rate limit is 1,000 requests per minute. Removal date is December 1, 2026.",
    )
    added = compare_typed_slots(added_prior, added_candidate)
    assert added is not None
    assert added.kind == "different_slot_added"
    assert added.slot == "deprecation_date"
    assert added.candidate_value == "2026-12-01"
    assert apply_typed_slot_evidence(typed=added) == "DETAIL"


def test_gold_ambiguous_extraction_does_not_force_revision():
    corpus = load_delta_adversarial_gold(_GOLD)
    case = corpus.case_by_id()["dag-p-026"]
    prior, candidate = _gold_extract(case)
    delta = typed_slots_as_revision_evidence(prior, candidate)

    assert prior.abstained is True
    assert candidate.abstained is True
    assert delta is None
    assert apply_typed_slot_evidence(typed=delta) is None
    assert case.equivalence == "uncertain"
    assert case.revision_class == "UNRESOLVED_CONTRADICTION"


def test_gold_numeric_family_covers_same_slot_changes_without_rewriting_labels():
    corpus = load_delta_adversarial_gold(_GOLD)
    changes = []
    for case in corpus.cases:
        if case.family != "numeric_version_date_unit":
            continue
        if case.revision_class not in {"STATE_UPDATE", "CORRECTION"}:
            continue
        prior, candidate = _gold_extract(case)
        assert prior.evidence_text == case.prior.detail
        assert candidate.evidence_text == case.candidate.detail
        delta = compare_typed_slots(prior, candidate)
        if delta is not None and delta.kind == "same_slot_value_change":
            changes.append(case.case_id)
            assert case.equivalence == "not_equivalent"

    assert len(changes) >= 3


def test_price_severity_platform_and_dates_extract_when_confident():
    result = extract_claim_slots(
        "Widget is supported on iOS. Price is $12/month. Severity: high. Effective March 1, 2026.",
        structured={"price": "$12/month", "severity": "high"},
        valid_at="2026-03-01T00:00:00Z",
    )

    assert result.slots_named("price")[0].value == "12"
    assert result.slots_named("price")[0].origin == "structured"
    assert result.slots_named("severity")[0].value == "high"
    assert result.slots_named("supported_platform")[0].value == "ios"
    assert result.slots_named("effective_date")[0].value == "2026-03-01"
    assert result.evidence_text.startswith("Widget is supported")


def test_conflicting_prose_values_abstain_for_that_slot():
    result = extract_claim_slots(
        "The limit is 100 MB and the limit is 200 GB.",
        detail_text="The limit is 100 MB and the limit is 200 GB.",
    )

    assert result.slots_named("limit") == ()
