import json
from pathlib import Path

from app.evaluation.claim_sequence import evaluate_claim_sequence
from app.evaluation.release_gate import require_release_gate
from app.services.github_advisory_pipeline import ingest_github_advisory_events
from app.stores.claim_ledger_store import ClaimLedgerStore

_CANONICAL_PREFIX = "canonical:github-advisory:"


def _ghsa_from_source_event_id(value: str) -> str:
    return value.removeprefix(_CANONICAL_PREFIX).upper()


def test_real_guzzle_advisory_bundle_reconciles_duplicates(database) -> None:
    path = Path(__file__).parent / "gold" / "github_advisory_guzzle_20260718.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    cases = bundle["cases"]

    assert bundle["provenance"]["captured_from_public_advisories"] is True
    assert len(cases) == 6

    result = ingest_github_advisory_events(
        database,
        advisories=[case["payload"] for case in cases],
        retrieved_at="2026-08-22T12:35:00Z",
        ecosystem=bundle["ecosystem"],
    )

    canonical_cases = [case for case in cases if case["role"] == "canonical"]
    duplicate_cases = [case for case in cases if case["role"] == "duplicate"]
    assert len(result.claim_ids) == len(canonical_cases) == 3
    assert len(result.event_ids) == 3

    with database.connect() as connection:
        claim_rows = connection.execute(
            """
            SELECT c.id AS claim_id, e.source_event_id
            FROM state_claims c
            JOIN ledger_events e ON e.id = c.event_id
            WHERE c.id IN (?, ?, ?)
            ORDER BY e.source_event_id
            """,
            tuple(result.claim_ids),
        ).fetchall()
        alias_rows = connection.execute(
            """
            SELECT alias_ghsa_id, canonical_ghsa_id, attached_claim_id
            FROM github_advisory_alias_evidence
            ORDER BY alias_ghsa_id
            """
        ).fetchall()
        event_states = connection.execute(
            """
            SELECT id, current_phase
            FROM events
            WHERE id IN (?, ?, ?)
            ORDER BY id
            """,
            tuple(result.event_ids),
        ).fetchall()

    claim_by_ghsa = {
        _ghsa_from_source_event_id(row["source_event_id"]): row["claim_id"]
        for row in claim_rows
    }
    expected_labels = {
        case["payload"]["ghsa_id"].upper(): case["event_label"]
        for case in canonical_cases
    }
    ordered_ghsas = sorted(claim_by_ghsa)
    report = evaluate_claim_sequence(
        database,
        bundle_id=bundle["bundle_id"],
        claim_ids=tuple(claim_by_ghsa[ghsa] for ghsa in ordered_ghsas),
        expected_revisions=tuple("NEW_FACT" for _ in ordered_ghsas),
        expected_event_labels=tuple(expected_labels[ghsa] for ghsa in ordered_ghsas),
    )

    assert report.revision_accuracy == 1.0
    assert report.delta_precision == 1.0
    assert report.delta_recall == 1.0
    assert report.repetition_rate == 0.0
    assert report.evidence_coverage == 1.0
    assert report.unsupported_claim_count == 0
    assert report.false_merge_count == 0
    assert report.false_split_count == 0
    require_release_gate(report)

    assert len(alias_rows) == len(duplicate_cases) == 3
    expected_alias_targets = {
        case["payload"]["ghsa_id"].upper(): case["payload"]["references"][0]["url"]
        .rsplit("/", 1)[-1]
        .upper()
        for case in duplicate_cases
    }
    for row in alias_rows:
        canonical_ghsa = expected_alias_targets[row["alias_ghsa_id"]]
        assert row["canonical_ghsa_id"] == canonical_ghsa
        assert row["attached_claim_id"] == claim_by_ghsa[canonical_ghsa]
        assert ClaimLedgerStore(database).independent_evidence_count(row["attached_claim_id"]) == 1

    assert {row["id"] for row in event_states} == set(result.event_ids)
    assert {row["current_phase"] for row in event_states} == {"active"}
