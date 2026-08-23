from app.services.github_advisory_pipeline import ingest_github_advisory_events
from app.stores.claim_ledger_store import ClaimLedgerStore

_CANONICAL_ID = "GHSA-h95v-h523-3mw8"
_DUPLICATE_ID = "GHSA-mqq9-gxg5-m58g"
_CANONICAL_KEY = _CANONICAL_ID.upper()
_DUPLICATE_KEY = _DUPLICATE_ID.upper()


def _canonical() -> dict:
    return {
        "ghsa_id": _CANONICAL_ID,
        "html_url": f"https://github.com/advisories/{_CANONICAL_ID}",
        "summary": "Guzzle: URI fragments disclosed in redirect Referer headers",
        "description": "The issue is fixed in Guzzle 7.15.1.",
        "severity": "moderate",
        "published_at": "2026-07-18T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
        "withdrawn_at": None,
        "references": [],
    }


def _duplicate() -> dict:
    return {
        "ghsa_id": _DUPLICATE_ID,
        "html_url": f"https://github.com/advisories/{_DUPLICATE_ID}",
        "summary": "Duplicate Advisory: Guzzle URI fragment disclosure",
        "description": f"This advisory was withdrawn because it is a duplicate of {_CANONICAL_ID}.",
        "severity": "high",
        "published_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-04T00:00:00Z",
        "withdrawn_at": "2026-08-04T00:00:00Z",
        "references": [{"url": f"https://github.com/advisories/{_CANONICAL_ID}"}],
    }


def test_duplicate_advisory_is_evidence_not_withdrawn_event(database) -> None:
    result = ingest_github_advisory_events(
        database,
        advisories=[_duplicate(), _canonical()],
        retrieved_at="2026-08-22T12:30:00Z",
        ecosystem="composer",
    )

    assert len(result.event_ids) == 1
    assert len(result.claim_ids) == 1
    claim_id = result.claim_ids[0]

    with database.connect() as connection:
        relations = connection.execute(
            "SELECT relation_type FROM claim_relations WHERE event_id = ?",
            (result.event_ids[0],),
        ).fetchall()
        deltas = connection.execute(
            "SELECT type FROM deltas WHERE event_id = ? AND active = 1",
            (result.event_ids[0],),
        ).fetchall()
        evidence = connection.execute(
            "SELECT dependence_key FROM claim_evidence WHERE claim_id = ? ORDER BY id",
            (claim_id,),
        ).fetchall()
        aliases = connection.execute(
            "SELECT alias_ghsa_id, canonical_ghsa_id, attached_claim_id "
            "FROM github_advisory_alias_evidence"
        ).fetchall()

    assert [row["relation_type"] for row in relations] == ["NEW_FACT"]
    assert [row["type"] for row in deltas] == ["new_fact"]
    assert len(evidence) == 2
    assert {row["dependence_key"] for row in evidence} == {f"advisory:{_CANONICAL_KEY}"}
    assert ClaimLedgerStore(database).independent_evidence_count(claim_id) == 1
    assert [tuple(row) for row in aliases] == [(_DUPLICATE_KEY, _CANONICAL_KEY, claim_id)]


def test_duplicate_advisory_can_arrive_before_canonical(database) -> None:
    pending = ingest_github_advisory_events(
        database,
        advisories=[_duplicate()],
        retrieved_at="2026-08-04T00:10:00Z",
        ecosystem="composer",
    )
    assert pending.event_ids == ()
    assert pending.claim_ids == ()

    canonical = ingest_github_advisory_events(
        database,
        advisories=[_canonical()],
        retrieved_at="2026-08-22T12:31:00Z",
        ecosystem="composer",
    )
    assert len(canonical.event_ids) == 1
    assert len(canonical.claim_ids) == 1

    with database.connect() as connection:
        alias = connection.execute(
            "SELECT attached_claim_id FROM github_advisory_alias_evidence WHERE alias_ghsa_id = ?",
            (_DUPLICATE_KEY,),
        ).fetchone()
        evidence_count = connection.execute(
            "SELECT COUNT(*) AS count FROM claim_evidence WHERE claim_id = ?",
            (canonical.claim_ids[0],),
        ).fetchone()["count"]
        event = connection.execute(
            "SELECT current_phase, current_confidence FROM events WHERE id = ?",
            (canonical.event_ids[0],),
        ).fetchone()

    assert alias["attached_claim_id"] == canonical.claim_ids[0]
    assert evidence_count == 2
    assert event["current_phase"] == "active"
    assert event["current_confidence"] == "high"
