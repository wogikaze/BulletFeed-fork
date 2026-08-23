from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def _summary():
    return {
        "incidents": [
            {
                "id": "inc_knownness",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_knownness",
                "incident_updates": [
                    {
                        "id": "upd_known_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_known_2",
                        "status": "identified",
                        "body": "Database saturation identified.",
                        "created_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:10:00Z",
                        "display_at": "2026-08-22T00:10:00Z",
                    },
                ],
            }
        ]
    }


def test_exposed_claims_become_known_without_cross_user_contamination(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_b', 0)")

    projector = FeedProjector(database)
    assert len(projector.project_event_for_user(user_id="user_a", event_id=event_id)) == 2
    assert len(projector.project_event_for_user(user_id="user_b", event_id=event_id)) == 2

    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "user_a",
        relation=None,
        item_status=None,
        cursor=None,
        limit=50,
    )
    assert len(delivered) == 2

    with database.connect() as connection:
        known_after_delivery = connection.execute(
            "SELECT COUNT(*) AS count FROM user_claim_exposures WHERE user_id = 'user_a'",
        ).fetchone()["count"]
    assert known_after_delivery == 0

    accepted = store.record_exposures(
        "user_a",
        [
            {
                "delivery_id": item.delivery_id,
                "displayed_at": "2026-08-22T00:12:00Z",
            }
            for item in delivered
        ],
    )
    assert accepted == 2

    with database.connect() as connection:
        known_a = connection.execute(
            "SELECT COUNT(*) AS count FROM user_claim_exposures WHERE user_id = 'user_a'",
        ).fetchone()["count"]
        known_b = connection.execute(
            "SELECT COUNT(*) AS count FROM user_claim_exposures WHERE user_id = 'user_b'",
        ).fetchone()["count"]
    assert known_a == 2
    assert known_b == 0

    assert projector.project_event_for_user(user_id="user_a", event_id=event_id) == []
    assert len(projector.project_event_for_user(user_id="user_b", event_id=event_id)) == 2
