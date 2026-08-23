from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def test_multisource_unresolved_conflict_is_delta_not_current_truth(database) -> None:
    release, feed = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id="release:42",
                payload={"id": 42, "tag_name": "v2.0.0"},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at="2026-08-22T10:00:00Z",
            ),
            NormalizedObservation(
                source_type="json_feed",
                source_key="https://status.acme.example/feed.json",
                source_observation_id="widget-v2-availability",
                payload={"id": "widget-v2-availability"},
                original_url="https://status.acme.example/widget-v2-availability",
                published_at="2026-08-22T11:00:00Z",
            ),
        ),
        retrieved_at="2026-08-22T11:05:00Z",
    )

    ledger = ClaimLedgerStore(database)
    first = ledger.ingest(
        release,
        source_event_id="release:42",
        canonical_event_key="acme/widget:v2-availability",
        title="acme/widget v2 availability",
        slot="availability",
        value="available",
        detail="GitHub Release reports v2 is available.",
        valid_at="2026-08-22T10:00:00Z",
        source_updated_at="2026-08-22T10:00:00Z",
        evidence_text="v2.0.0 was published.",
    )
    conflict = ledger.ingest(
        feed,
        source_event_id="widget-v2-availability",
        canonical_event_key="acme/widget:v2-availability",
        title="acme/widget v2 availability",
        slot="availability",
        value="unavailable",
        detail="Official status feed reports v2 is not yet available.",
        valid_at="2026-08-22T11:00:00Z",
        source_updated_at="2026-08-22T11:00:00Z",
        evidence_text="Status feed reports the release is not yet available.",
        unresolved_source_conflict=True,
    )

    assert first.event_id == conflict.event_id
    assert first.relation_type == "NEW_FACT"
    assert conflict.relation_type == "UNRESOLVED_CONTRADICTION"

    LedgerProjector(database).project_event(first.event_id)

    with database.connect() as connection:
        event = connection.execute(
            "SELECT * FROM events WHERE id = ?",
            (first.event_id,),
        ).fetchone()
        deltas = connection.execute(
            "SELECT type, before_text, after_text FROM deltas "
            "WHERE event_id = ? AND active = 1 ORDER BY occurred_at, id",
            (first.event_id,),
        ).fetchall()
        sources = connection.execute(
            "SELECT kind FROM event_sources WHERE event_id = ? ORDER BY kind",
            (first.event_id,),
        ).fetchall()

    assert event["current_phase"] == "available"
    assert event["current_summary"] == "GitHub Release reports v2 is available."
    assert event["current_since"] == "2026-08-22T10:00:00Z"
    assert event["current_confidence"] == "low"
    assert [row["type"] for row in deltas] == ["new_fact", "unresolved_contradiction"]
    assert deltas[-1]["before_text"] == "available"
    assert deltas[-1]["after_text"] == "unavailable"
    assert {row["kind"] for row in sources} == {"github_release", "json_feed"}


def test_conflict_hint_survives_out_of_order_relation_rebuild(database) -> None:
    earlier, later = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id="release:42",
                payload={"id": 42},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at="2026-08-22T10:00:00Z",
            ),
            NormalizedObservation(
                source_type="rss_atom",
                source_key="https://status.acme.example/feed.xml",
                source_observation_id="availability-42",
                payload={"id": "availability-42"},
                original_url="https://status.acme.example/availability-42",
                published_at="2026-08-22T11:00:00Z",
            ),
        ),
        retrieved_at="2026-08-22T11:05:00Z",
    )
    ledger = ClaimLedgerStore(database)

    later_claim = ledger.ingest(
        later,
        source_event_id="availability-42",
        canonical_event_key="acme/widget:v2-availability-replay",
        title="acme/widget v2 availability replay",
        slot="availability",
        value="unavailable",
        detail="Status feed says unavailable.",
        valid_at="2026-08-22T11:00:00Z",
        evidence_text="Status feed says unavailable.",
        unresolved_source_conflict=True,
    )
    ledger.ingest(
        earlier,
        source_event_id="release:42",
        canonical_event_key="acme/widget:v2-availability-replay",
        title="acme/widget v2 availability replay",
        slot="availability",
        value="available",
        detail="GitHub Release says available.",
        valid_at="2026-08-22T10:00:00Z",
        evidence_text="GitHub Release says available.",
    )

    with database.connect() as connection:
        relation = connection.execute(
            "SELECT relation_type FROM claim_relations WHERE new_claim_id = ?",
            (later_claim.claim_id,),
        ).fetchone()

    assert relation["relation_type"] == "UNRESOLVED_CONTRADICTION"
