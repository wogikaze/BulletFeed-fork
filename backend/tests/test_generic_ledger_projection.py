from pathlib import Path

from app.database import Database
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def test_projector_handles_github_release_claims(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
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
    claim = ClaimLedgerStore(database).ingest(
        observation,
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="v2.0.0 published",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="v2.0.0 published",
    )

    LedgerProjector(database).project_event(claim.event_id)

    with database.connect() as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (claim.event_id,)).fetchone()
        delta = connection.execute("SELECT * FROM deltas WHERE event_id = ?", (claim.event_id,)).fetchone()
        source = connection.execute(
            "SELECT * FROM event_sources WHERE event_id = ?",
            (claim.event_id,),
        ).fetchone()

    assert event["current_phase"] == "released"
    assert delta["type"] == "new_fact"
    assert source["publisher"] == "GitHub"
    assert source["kind"] == "github_release"
