from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline


def _summary():
    return {
        "incidents": [
            {
                "id": "inc_1",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_1",
                "incident_updates": [
                    {
                        "id": "upd_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_2",
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


def test_feed_projection_creates_one_item_per_novel_delta(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")

    item_ids = FeedProjector(database).project_event_for_user(user_id="user_1", event_id=event_id)

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM feed_items WHERE user_id = 'user_1' AND event_id = ? ORDER BY updated_at",
            (event_id,),
        ).fetchall()
    assert len(rows) == 2
    assert len(item_ids) == 2
    assert all(row["relation_level"] == "reference" for row in rows)
    assert [row["importance_level"] for row in rows] == ["medium", "medium"]
    assert [row["importance_confidence"] for row in rows] == ["medium", "high"]


def test_feed_projection_is_idempotent(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")

    projector = FeedProjector(database)
    first = projector.project_event_for_user(user_id="user_1", event_id=event_id)
    second = projector.project_event_for_user(user_id="user_1", event_id=event_id)

    assert second == first
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchone()["count"]
    assert count == 2
