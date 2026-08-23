from app.services.semantic_delta import ClaimSnapshot, DeltaContext, classify_revision


def claim(value: str, detail: str = "", valid_at: str = "2026-08-22T00:00:00Z"):
    return ClaimSnapshot(value=value, detail=detail, valid_at=valid_at)


def test_first_claim_is_new_fact():
    assert classify_revision(None, claim("investigating")) == "NEW_FACT"


def test_exact_semantic_repeat_is_non_novel():
    prior = claim("identified", "Database saturation.")
    assert classify_revision(prior, claim("identified", "Database saturation.")) == "NON_NOVEL"


def test_same_state_with_added_information_is_detail():
    prior = claim("identified", "Issue identified.")
    assert classify_revision(prior, claim("identified", "Database saturation identified.")) == "DETAIL"


def test_later_mutable_state_change_is_state_update():
    prior = claim("identified", valid_at="2026-08-22T00:10:00Z")
    candidate = claim("monitoring", valid_at="2026-08-22T00:20:00Z")
    assert classify_revision(prior, candidate) == "STATE_UPDATE"


def test_same_valid_time_conflict_is_not_mislabeled_as_state_update():
    prior = claim("operational")
    candidate = claim("degraded")
    assert classify_revision(prior, candidate) == "UNRESOLVED_CONTRADICTION"


def test_explicit_correction_overrides_textual_conflict():
    prior = claim("resolved")
    candidate = claim("monitoring")
    assert (
        classify_revision(prior, candidate, context=DeltaContext(explicit_correction=True))
        == "CORRECTION"
    )


def test_source_conflict_remains_unresolved_without_supersession_evidence():
    prior = claim("resolved")
    candidate = claim("monitoring", valid_at="2026-08-22T00:30:00Z")
    assert (
        classify_revision(
            prior,
            candidate,
            context=DeltaContext(unresolved_source_conflict=True),
        )
        == "UNRESOLVED_CONTRADICTION"
    )
