from app.services.claim_semantics import canonicalize_text, compare_claims


def test_numeric_and_unit_formatting_are_canonicalized():
    left = canonicalize_text("Limit increased to 1,000 requests per minute.")
    right = canonicalize_text("Limit was raised to one thousand requests/min.")

    assert left.text == right.text
    assert compare_claims(left.text, "", right.text, "").label == "equivalent"


def test_date_formats_are_canonicalized():
    assert canonicalize_text("Retires July 30, 2026").text == canonicalize_text(
        "Retires 2026/07/30"
    ).text


def test_entity_aliases_are_explicit_and_deterministic():
    aliases = {"postgres": "postgresql"}
    left = canonicalize_text("Postgres migration", entity_aliases=aliases)
    right = canonicalize_text("PostgreSQL migration", entity_aliases=aliases)

    assert left.text == right.text


def test_reordered_facts_are_equivalent():
    decision = compare_claims(
        "available",
        "Japan rollout is available for enterprise users",
        "available",
        "Enterprise users have Japan rollout available",
    )

    assert decision.label == "equivalent"
    assert decision.confidence in {"high", "medium"}


def test_added_detail_is_not_equivalent_restatement():
    decision = compare_claims(
        "released",
        "Widget v3 is available",
        "released",
        "Widget v3 is available with migration notes",
    )

    assert decision.label == "not_equivalent"
    assert "detail" in decision.reason


def test_numeric_change_is_not_equivalent():
    decision = compare_claims(
        "limit 1000 requests/min",
        "",
        "limit 1200 requests/min",
        "",
    )

    assert decision.label == "not_equivalent"
    assert "numeric" in decision.reason


def test_version_change_is_not_equivalent():
    decision = compare_claims("fixed in v2.1.0", "", "fixed in v2.2.0", "")

    assert decision.label == "not_equivalent"
    assert "version" in decision.reason


def test_negation_is_never_normalized_away():
    decision = compare_claims("Python 3.10 is supported", "", "Python 3.10 is not supported", "")

    assert decision.label == "not_equivalent"
    assert "negation" in decision.reason


def test_inconclusive_semantics_return_uncertain():
    decision = compare_claims(
        "database latency issue",
        "",
        "database capacity issue",
        "",
    )

    assert decision.label == "uncertain"
    assert decision.confidence == "low"
