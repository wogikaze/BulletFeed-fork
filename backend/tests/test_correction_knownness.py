from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def _summary(body: str, *, updated_at: str) -> dict:
    return {
        "incidents": [
            {
                "id": "inc_correction_knownness",
                "name": "API availability",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_correction_knownness",
                "incident_updates": [
                    {
                        "id": "upd_correction_knownness",
                        "status": "identified",
                        "body": body,
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": updated_at,
                        "display_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def _expose_all(store: FeedStore, user_id: str, *, displayed_at: str) -> None:
    delivered, _ = store.list_feed(
        user_id,
        relation=None,
        item_status=None,
        cursor=None,
        limit=50,
    )
    assert delivered
    accepted = store.record_exposures(
        user_id,
        [
            {
                "delivery_id": item.delivery_id,
                "displayed_at": displayed_at,
                "dwell_ms": 1200,
                "visible_ratio": 0.8,
            }
            for item in delivered
        ],
    )
    assert accepted == len(delivered)


def test_known_user_receives_later_correction_without_reprojecting_known_claim(database) -> None:
    pipeline = StatuspagePipeline(database)
    first = pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "Requests from Europe are affected.",
            updated_at="2026-08-22T00:00:00Z",
        ),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    event_id = first.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_b', 0)")

    projector = FeedProjector(database)
    first_user_a = projector.project_event_for_user(user_id="user_a", event_id=event_id)
    assert len(first_user_a) == 1
    projector.project_event_for_user(user_id="user_b", event_id=event_id)

    store = FeedStore(database)
    _expose_all(store, "user_a", displayed_at="2026-08-22T00:02:00Z")

    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "Correction: the previous update was incorrect. Requests from Asia are affected.",
            updated_at="2026-08-22T00:10:00Z",
        ),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    LedgerProjector(database).project_event(event_id)

    new_for_a = projector.project_event_for_user(user_id="user_a", event_id=event_id)
    all_unknown_for_b = projector.project_event_for_user(user_id="user_b", event_id=event_id)

    assert len(new_for_a) == 1
    assert len(all_unknown_for_b) == 2
    with database.connect() as connection:
        projected = connection.execute(
            """
            SELECT d.type, m.claim_id
            FROM feed_items f
            JOIN deltas d ON d.id = f.delta_id
            JOIN delta_claim_map m ON m.delta_id = d.id
            WHERE f.id = ?
            """,
            (new_for_a[0],),
        ).fetchone()
        known_claims = {
            row["claim_id"]
            for row in connection.execute(
                """
                SELECT claim_id FROM user_claim_exposures
                WHERE user_id = 'user_a' AND state IN ('displayed', 'read')
                """
            ).fetchall()
        }

    assert projected["type"] == "correction"
    assert projected["claim_id"] not in known_claims


def test_delayed_old_update_does_not_reopen_known_user_feed(database) -> None:
    pipeline = StatuspagePipeline(database)
    current = {
        "incidents": [
            {
                "id": "inc_delayed_knownness",
                "name": "API availability",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_delayed_knownness",
                "incident_updates": [
                    {
                        "id": "upd_current",
                        "status": "resolved",
                        "body": "Service has recovered.",
                        "created_at": "2026-08-22T00:20:00Z",
                        "updated_at": "2026-08-22T00:20:00Z",
                        "display_at": "2026-08-22T00:20:00Z",
                    }
                ],
            }
        ]
    }
    result = pipeline.ingest_summary(
        page_id="abcd1234",
        summary=current,
        retrieved_at="2026-08-22T00:21:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")

    projector = FeedProjector(database)
    projector.project_event_for_user(user_id="user_a", event_id=event_id)
    _expose_all(FeedStore(database), "user_a", displayed_at="2026-08-22T00:22:00Z")

    delayed = {
        "incidents": [
            {
                "id": "inc_delayed_knownness",
                "name": "API availability",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_delayed_knownness",
                "incident_updates": [
                    {
                        "id": "upd_delayed_old",
                        "status": "investigating",
                        "body": "Investigating connectivity failures.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    current["incidents"][0]["incident_updates"][0],
                ],
            }
        ]
    }
    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=delayed,
        retrieved_at="2026-08-22T00:30:00Z",
    )
    LedgerProjector(database).project_event(event_id)

    new_items = projector.project_event_for_user(user_id="user_a", event_id=event_id)

    # The delayed historical claim was never exposed before, but it is older than
    # the user's known current state and must not be surfaced as a fresh update.
    assert new_items == []
