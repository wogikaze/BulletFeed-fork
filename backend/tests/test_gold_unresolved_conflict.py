import json
from pathlib import Path

from app.evaluation.claim_sequence import evaluate_claim_sequence
from app.evaluation.release_gate import require_release_gate
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def test_unresolved_conflict_gold_passes_release_gate(database) -> None:
    path = Path(__file__).parent / "gold" / "unresolved_conflict_pilot_001.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))

    claim_ids: list[str] = []
    expected_revisions: list[str] = []
    expected_event_labels: list[str] = []
    event_ids: set[str] = set()

    ingestion = SourceIngestionPipeline(database)
    ledger = ClaimLedgerStore(database)
    for case in bundle["cases"]:
        observation = ingestion.ingest_many(
            (
                NormalizedObservation(
                    source_type=case["source_type"],
                    source_key=case["source_key"],
                    source_observation_id=case["source_observation_id"],
                    payload={"id": case["source_observation_id"]},
                    original_url=case["original_url"],
                    published_at=case["published_at"],
                ),
            ),
            retrieved_at=case["retrieved_at"],
        )[0]
        claim = ledger.ingest(
            observation,
            source_event_id=case["source_event_id"],
            canonical_event_key=case["canonical_event_key"],
            title=case["title"],
            slot=case["slot"],
            value=case["value"],
            detail=case["detail"],
            valid_at=case["valid_at"],
            source_updated_at=case["source_updated_at"],
            evidence_text=case["evidence_text"],
            unresolved_source_conflict=case["unresolved_source_conflict"],
        )
        claim_ids.append(claim.claim_id)
        expected_revisions.append(case["expected_revision"])
        expected_event_labels.append(case["event_label"])
        event_ids.add(claim.event_id)

    projector = LedgerProjector(database)
    for event_id in event_ids:
        projector.project_event(event_id)

    report = evaluate_claim_sequence(
        database,
        bundle_id=bundle["bundle_id"],
        claim_ids=tuple(claim_ids),
        expected_revisions=tuple(expected_revisions),
        expected_event_labels=tuple(expected_event_labels),
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

    with database.connect() as connection:
        event = connection.execute(
            """
            SELECT e.*
            FROM events e
            JOIN state_claims c ON c.event_id = e.id
            WHERE c.id = ?
            """,
            (claim_ids[0],),
        ).fetchone()
    assert event["current_phase"] == "available"
    assert event["current_summary"] == "GitHub Release confirms v2 is available in all regions."
    assert event["current_confidence"] == "high"
