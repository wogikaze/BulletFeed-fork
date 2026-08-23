from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def _append_release_observation(database, *, observation_id: str, published_at: str):
    return SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id=observation_id,
                payload={"id": 42, "tag_name": "v2.0.0"},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at=published_at,
            ),
        ),
        retrieved_at="2026-08-22T10:05:00Z",
    )[0]


def test_non_novel_reobservation_does_not_move_current_since(database):
    ledger = ClaimLedgerStore(database)

    later = ledger.ingest(
        _append_release_observation(
            database,
            observation_id="release:42:later",
            published_at="2026-08-22T10:00:00Z",
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
    LedgerProjector(database).project_event(later.event_id)

    earlier = ledger.ingest(
        _append_release_observation(
            database,
            observation_id="release:42:earlier",
            published_at="2026-08-22T09:00:00Z",
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
    assert earlier.relation_type == "NEW_FACT"

    LedgerProjector(database).project_event(later.event_id)

    with database.connect() as connection:
        event = connection.execute(
            "SELECT current_phase, current_since, updated_at FROM events WHERE id = ?",
            (later.event_id,),
        ).fetchone()
        later_relation = connection.execute(
            "SELECT relation_type FROM claim_relations WHERE new_claim_id = ?",
            (later.claim_id,),
        ).fetchone()

    assert later_relation["relation_type"] == "NON_NOVEL"
    assert event["current_phase"] == "released"
    assert event["current_since"] == "2026-08-22T09:00:00Z"
    assert event["updated_at"] == "2026-08-22T10:00:00Z"
