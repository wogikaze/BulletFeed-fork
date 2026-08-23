from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore
from app.stores.event_store import EventStore
from app.stores.feed_store import FeedStore


def _observation(database, *, observation_id: str, published_at: str, retrieved_at: str):
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
        retrieved_at=retrieved_at,
    )[0]


def test_delayed_observation_reconciles_stale_public_delta(database):
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_replay', 0)")

    ledger = ClaimLedgerStore(database)
    projector = LedgerProjector(database)

    later_observation = _observation(
        database,
        observation_id="release:42:later",
        published_at="2026-08-22T10:00:00Z",
        retrieved_at="2026-08-22T10:01:00Z",
    )
    later_claim = ledger.ingest(
        later_observation,
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="v2.0.0 published",
        valid_at="2026-08-22T10:00:00Z",
        source_updated_at="2026-08-22T10:00:00Z",
        evidence_text="v2.0.0 published",
    )
    assert later_claim.relation_type == "NEW_FACT"

    projector.project_event(later_claim.event_id)
    first_feed_items = FeedProjector(database).project_event_for_user(
        user_id="user_replay",
        event_id=later_claim.event_id,
    )
    assert len(first_feed_items) == 1

    with database.connect() as connection:
        stale_delta = connection.execute(
            "SELECT id FROM deltas WHERE event_id = ? AND active = 1",
            (later_claim.event_id,),
        ).fetchone()
        assert stale_delta is not None
        stale_delta_id = stale_delta["id"]

    earlier_observation = _observation(
        database,
        observation_id="release:42:earlier",
        published_at="2026-08-22T09:00:00Z",
        retrieved_at="2026-08-22T10:05:00Z",
    )
    earlier_claim = ledger.ingest(
        earlier_observation,
        source_event_id="release:42",
        title="acme/widget v2.0.0",
        slot="release_state",
        value="released",
        detail="v2.0.0 published",
        valid_at="2026-08-22T09:00:00Z",
        source_updated_at="2026-08-22T09:00:00Z",
        evidence_text="v2.0.0 published",
    )
    assert earlier_claim.relation_type == "NEW_FACT"

    with database.connect() as connection:
        later_relation = connection.execute(
            "SELECT relation_type FROM claim_relations WHERE new_claim_id = ?",
            (later_claim.claim_id,),
        ).fetchone()
        assert later_relation["relation_type"] == "NON_NOVEL"

    projector.project_event(later_claim.event_id)

    with database.connect() as connection:
        active_deltas = connection.execute(
            """
            SELECT d.id, m.claim_id
            FROM deltas d
            JOIN delta_claim_map m ON m.delta_id = d.id
            WHERE d.event_id = ? AND d.active = 1
            """,
            (later_claim.event_id,),
        ).fetchall()
        inactive = connection.execute(
            "SELECT active FROM deltas WHERE id = ?",
            (stale_delta_id,),
        ).fetchone()
        timeline = connection.execute(
            "SELECT delta_id FROM event_timeline WHERE event_id = ?",
            (later_claim.event_id,),
        ).fetchall()
        sources = connection.execute(
            """
            SELECT m.claim_id
            FROM event_sources s
            JOIN event_source_claim_map m ON m.source_id = s.id
            WHERE s.event_id = ?
            """,
            (later_claim.event_id,),
        ).fetchall()
        stale_feed = connection.execute(
            "SELECT dismissed FROM feed_items WHERE id = ?",
            (first_feed_items[0],),
        ).fetchone()

    assert [(row["claim_id"]) for row in active_deltas] == [earlier_claim.claim_id]
    assert inactive["active"] == 0
    assert [row["delta_id"] for row in timeline] == [active_deltas[0]["id"]]
    assert [row["claim_id"] for row in sources] == [earlier_claim.claim_id]
    assert stale_feed["dismissed"] == 1

    detail = EventStore(database).get_event("user_replay", later_claim.event_id, None)
    assert detail.latest_delta.id == active_deltas[0]["id"]

    projected = FeedProjector(database).project_event_for_user(
        user_id="user_replay",
        event_id=later_claim.event_id,
    )
    assert len(projected) == 1

    items, _ = FeedStore(database).list_feed(
        "user_replay",
        relation=None,
        item_status=None,
        cursor=None,
        limit=20,
    )
    assert [item.delta.id for item in items] == [active_deltas[0]["id"]]
