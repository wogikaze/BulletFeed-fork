from pathlib import Path

from app.database import Database
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def test_claim_ledger_promotes_observation_to_event_claim_and_evidence(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    observation = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id="release:42",
                payload={"id": 42, "tag_name": "v2.0.0"},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at="2026-08-20T10:00:00Z",
            ),
        ),
        retrieved_at="2026-08-20T10:01:00Z",
    )[0]

    store = ClaimLedgerStore(database)
    first = store.ingest(
        observation,
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="v2.0.0 published",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="v2.0.0 published",
    )
    second = store.ingest(
        observation,
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="v2.0.0 published",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="v2.0.0 published",
    )

    assert first == second
    assert first.relation_type == "NEW_FACT"
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM claim_relations").fetchone()[0] == 1


def test_claim_ledger_uses_source_revision_time_and_correction_hint(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    observations = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id="release:42",
                payload={"id": 42, "body": "initial"},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at="2026-08-20T10:00:00Z",
            ),
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id="release:42",
                payload={"id": 42, "body": "corrected"},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at="2026-08-20T10:00:00Z",
            ),
        ),
        retrieved_at="2026-08-20T10:10:00Z",
    )

    store = ClaimLedgerStore(database)
    store.ingest(
        observations[0],
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="initial",
        valid_at="2026-08-20T10:00:00Z",
        source_updated_at="2026-08-20T10:01:00Z",
        evidence_text="initial",
    )
    corrected = store.ingest(
        observations[1],
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="corrected",
        valid_at="2026-08-20T10:00:00Z",
        source_updated_at="2026-08-20T10:05:00Z",
        evidence_text="corrected",
        explicit_correction=True,
    )

    assert corrected.source_updated_at == "2026-08-20T10:05:00Z"
    assert corrected.relation_type == "CORRECTION"
