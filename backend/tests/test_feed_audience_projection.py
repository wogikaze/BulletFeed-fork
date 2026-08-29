from app.services.feed_projection import FeedProjector, project_event_for_audience
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def _summary():
    return {
        "incidents": [
            {
                "id": "inc_audience",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_audience",
                "incident_updates": [
                    {
                        "id": "upd_audience_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_audience_2",
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


def _projected_event(database) -> str:
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
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_outsider', 0)")
    return event_id


def test_explicit_audience_matches_direct_project_event_for_user(database):
    event_id = _projected_event(database)

    by_user = project_event_for_audience(database, event_id=event_id, user_ids=("user_a",))
    direct = FeedProjector(database).project_event_for_user(user_id="user_a", event_id=event_id)

    assert list(by_user["user_a"]) == direct
    assert len(by_user["user_a"]) == 2
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT user_id, delta_id
            FROM feed_items
            WHERE event_id = ?
            ORDER BY user_id, delta_id
            """,
            (event_id,),
        ).fetchall()
    assert {row["user_id"] for row in rows} == {"user_a"}
    assert len(rows) == 2


def test_audience_projection_is_idempotent_at_user_and_delta(database):
    event_id = _projected_event(database)

    first = project_event_for_audience(
        database,
        event_id=event_id,
        user_ids=("user_a", "user_b", "user_a"),
    )
    second = project_event_for_audience(
        database,
        event_id=event_id,
        user_ids=("user_a", "user_b"),
    )

    assert second == first
    with database.connect() as connection:
        pairs = connection.execute(
            """
            SELECT user_id, delta_id, COUNT(*) AS count
            FROM feed_items
            WHERE event_id = ?
            GROUP BY user_id, delta_id
            """,
            (event_id,),
        ).fetchall()
        total = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE event_id = ?",
            (event_id,),
        ).fetchone()["count"]
    assert total == 4
    assert all(row["count"] == 1 for row in pairs)
    assert {(row["user_id"], row["delta_id"]) for row in pairs} == {
        (row["user_id"], row["delta_id"]) for row in pairs
    }


def test_user_outside_audience_receives_no_feed_item(database):
    event_id = _projected_event(database)

    project_event_for_audience(database, event_id=event_id, user_ids=("user_a",))

    with database.connect() as connection:
        outsider = connection.execute(
            """
            SELECT COUNT(*) AS count FROM feed_items
            WHERE user_id = 'user_outsider' AND event_id = ?
            """,
            (event_id,),
        ).fetchone()["count"]
        audience = connection.execute(
            """
            SELECT COUNT(*) AS count FROM feed_items
            WHERE user_id = 'user_a' AND event_id = ?
            """,
            (event_id,),
        ).fetchone()["count"]
    assert audience == 2
    assert outsider == 0


def test_list_feed_writes_delivered_not_watermark_knownness(database):
    event_id = _projected_event(database)
    project_event_for_audience(database, event_id=event_id, user_ids=("user_a",))

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
        known_after_list = connection.execute(
            """
            SELECT COUNT(*) AS count FROM user_claim_exposures
            WHERE user_id = 'user_a' AND state IN ('displayed', 'read')
            """,
        ).fetchone()["count"]
        delivered_after_list = connection.execute(
            """
            SELECT COUNT(*) AS count FROM user_claim_exposures
            WHERE user_id = 'user_a' AND state = 'delivered'
            """,
        ).fetchone()["count"]
        deliveries = connection.execute(
            "SELECT COUNT(*) AS count FROM deliveries WHERE user_id = 'user_a'",
        ).fetchone()["count"]
    assert known_after_list == 0
    assert delivered_after_list == 2
    assert deliveries == 2

    accepted = store.record_exposures(
        "user_a",
        [
            {"delivery_id": item.delivery_id, "displayed_at": "2026-08-22T00:12:00Z"}
            for item in delivered
        ],
    )
    assert accepted == 2
    with database.connect() as connection:
        known_after_record = connection.execute(
            """
            SELECT COUNT(*) AS count FROM user_claim_exposures
            WHERE user_id = 'user_a' AND state IN ('displayed', 'read')
            """,
        ).fetchone()["count"]
    assert known_after_record == 2
