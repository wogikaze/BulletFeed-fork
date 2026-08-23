from app.evaluation.claim_sequence import evaluate_claim_sequence
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def _observation(database, *, observation_id: str, valid_at: str):
    return SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id=observation_id,
                payload={"id": 42, "tag_name": "v2.0.0"},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at=valid_at,
            ),
        ),
        retrieved_at="2026-08-22T10:05:00Z",
    )[0]


def test_gold_metrics_ignore_delta_deactivated_by_replay(database):
    ledger = ClaimLedgerStore(database)
    projector = LedgerProjector(database)

    later = ledger.ingest(
        _observation(
            database,
            observation_id="release:42:later",
            valid_at="2026-08-22T10:00:00Z",
        ),
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="v2.0.0 published",
        valid_at="2026-08-22T10:00:00Z",
        source_updated_at="2026-08-22T10:00:00Z",
        evidence_text="v2.0.0 published",
    )
    projector.project_event(later.event_id)

    earlier = ledger.ingest(
        _observation(
            database,
            observation_id="release:42:earlier",
            valid_at="2026-08-22T09:00:00Z",
        ),
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="v2.0.0 published",
        valid_at="2026-08-22T09:00:00Z",
        source_updated_at="2026-08-22T09:00:00Z",
        evidence_text="v2.0.0 published",
    )
    projector.project_event(later.event_id)

    report = evaluate_claim_sequence(
        database,
        bundle_id="replay-active-delta",
        claim_ids=(later.claim_id, earlier.claim_id),
        expected_revisions=("NON_NOVEL", "NEW_FACT"),
        expected_event_labels=("release-42", "release-42"),
    )

    assert report.revision_accuracy == 1.0
    assert report.delta_precision == 1.0
    assert report.delta_recall == 1.0
    assert report.repetition_rate == 0.0
    assert report.evidence_coverage == 1.0
    assert report.unsupported_claim_count == 0
