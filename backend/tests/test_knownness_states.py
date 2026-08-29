from pydantic import ValidationError

from app.db.knownness import UNDISPLAYED_DELIVERY_RETRY_LIMIT
from app.schemas.feed import ExposuresRequest
from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def _summary(incident_id: str, updates: list[dict]) -> dict:
    return {
        "incidents": [
            {
                "id": incident_id,
                "name": "API availability",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": f"https://stspg.io/{incident_id}",
                "incident_updates": updates,
            }
        ]
    }


def _update(update_id: str, body: str, at: str, *, status: str = "identified") -> dict:
    return {
        "id": update_id,
        "status": status,
        "body": body,
        "created_at": at,
        "updated_at": at,
        "display_at": at,
    }


def _prepare_users(database, event_id: str, *user_ids: str) -> FeedProjector:
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        for user_id in user_ids:
            connection.execute(
                "INSERT INTO users (id, created_at) VALUES (?, 0)",
                (user_id,),
            )
    projector = FeedProjector(database)
    for user_id in user_ids:
        projector.project_event_for_user(user_id=user_id, event_id=event_id)
    return projector


def _states(database, user_id: str) -> dict[str, str]:
    with database.connect() as connection:
        return {
            row["claim_id"]: row["state"]
            for row in connection.execute(
                """
                SELECT claim_id, state
                FROM user_claim_exposures
                WHERE user_id = ?
                """,
                (user_id,),
            )
        }


def _watermark_ids(database, user_id: str) -> set[str]:
    with database.connect() as connection:
        return {
            row["claim_id"]
            for row in connection.execute(
                """
                SELECT claim_id FROM user_claim_exposures
                WHERE user_id = ? AND state IN ('displayed', 'read')
                """,
                (user_id,),
            )
        }


def test_delivered_not_displayed_does_not_advance_watermark_and_retries(database) -> None:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "inc_delivered",
            [_update("upd_delivered", "Investigating elevated latency.", "2026-08-22T00:00:00Z")],
        ),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    event_id = result.event_ids[0]
    projector = _prepare_users(database, event_id, "user_a")
    store = FeedStore(database)

    first, _ = store.list_feed(
        "user_a", relation=None, item_status=None, cursor=None, limit=50
    )
    assert len(first) == 1
    assert all(state == "delivered" for state in _states(database, "user_a").values())
    assert _watermark_ids(database, "user_a") == set()
    assert projector.project_event_for_user(user_id="user_a", event_id=event_id)

    for _ in range(UNDISPLAYED_DELIVERY_RETRY_LIMIT - 1):
        page, _ = store.list_feed(
            "user_a", relation=None, item_status=None, cursor=None, limit=50
        )
        assert [item.id for item in page] == [first[0].id]

    exhausted, _ = store.list_feed(
        "user_a", relation=None, item_status=None, cursor=None, limit=50
    )
    assert exhausted == []
    assert _watermark_ids(database, "user_a") == set()
    assert projector.project_event_for_user(user_id="user_a", event_id=event_id)


def test_displayed_advances_watermark_and_is_idempotent_across_deliveries(database) -> None:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "inc_displayed",
            [_update("upd_displayed", "Investigating elevated latency.", "2026-08-22T00:00:00Z")],
        ),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    event_id = result.event_ids[0]
    projector = _prepare_users(database, event_id, "user_a")
    store = FeedStore(database)

    first, _ = store.list_feed(
        "user_a", relation=None, item_status=None, cursor=None, limit=50
    )
    second, _ = store.list_feed(
        "user_a", relation=None, item_status=None, cursor=None, limit=50
    )
    assert first[0].delivery_id != second[0].delivery_id

    accepted = store.record_exposures(
        "user_a",
        [
            {"delivery_id": first[0].delivery_id, "displayed_at": "2026-08-22T00:02:00Z"},
            {"delivery_id": second[0].delivery_id, "displayed_at": "2026-08-22T00:03:00Z"},
            {"delivery_id": first[0].delivery_id, "displayed_at": "2026-08-22T00:04:00Z"},
        ],
    )
    assert accepted == 2
    assert set(_states(database, "user_a").values()) == {"displayed"}
    assert projector.project_event_for_user(user_id="user_a", event_id=event_id) == []

    replay = store.record_exposures(
        "user_a",
        [{"delivery_id": first[0].delivery_id, "displayed_at": "2026-08-22T00:05:00Z"}],
    )
    assert replay == 0
    with database.connect() as connection:
        displayed_at = connection.execute(
            "SELECT displayed_at FROM user_claim_exposures WHERE user_id = 'user_a'"
        ).fetchone()["displayed_at"]
    assert displayed_at == "2026-08-22T00:02:00Z"


def test_read_advances_watermark_without_display(database) -> None:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "inc_read",
            [_update("upd_read", "Investigating elevated latency.", "2026-08-22T00:00:00Z")],
        ),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    event_id = result.event_ids[0]
    projector = _prepare_users(database, event_id, "user_a")
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "user_a", relation=None, item_status=None, cursor=None, limit=50
    )
    assert delivered
    store.mark_read("user_a", delivered[0].id)

    assert set(_states(database, "user_a").values()) == {"read"}
    assert _watermark_ids(database, "user_a")
    assert projector.project_event_for_user(user_id="user_a", event_id=event_id) == []


def test_delayed_historical_claim_stays_suppressed_after_displayed(database) -> None:
    pipeline = StatuspagePipeline(database)
    current = _update(
        "upd_current",
        "Service has recovered.",
        "2026-08-22T00:20:00Z",
        status="resolved",
    )
    result = pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary("inc_delayed_states", [current]),
        retrieved_at="2026-08-22T00:21:00Z",
    )
    event_id = result.event_ids[0]
    projector = _prepare_users(database, event_id, "user_a")
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "user_a", relation=None, item_status=None, cursor=None, limit=50
    )
    assert delivered
    accepted = store.record_exposures(
        "user_a",
        [{"delivery_id": item.delivery_id, "displayed_at": "2026-08-22T00:22:00Z"} for item in delivered],
    )
    assert accepted == len(delivered)
    assert _watermark_ids(database, "user_a")

    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "inc_delayed_states",
            [
                _update(
                    "upd_delayed_old",
                    "Investigating connectivity failures.",
                    "2026-08-22T00:00:00Z",
                    status="investigating",
                ),
                current,
            ],
        ),
        retrieved_at="2026-08-22T00:30:00Z",
    )
    LedgerProjector(database).project_event(event_id)
    assert projector.project_event_for_user(user_id="user_a", event_id=event_id) == []


def test_delayed_historical_claim_can_appear_after_delivered_only(database) -> None:
    pipeline = StatuspagePipeline(database)
    current = _update(
        "upd_current_delivered",
        "Service has recovered.",
        "2026-08-22T00:20:00Z",
        status="resolved",
    )
    result = pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary("inc_delayed_delivered", [current]),
        retrieved_at="2026-08-22T00:21:00Z",
    )
    event_id = result.event_ids[0]
    projector = _prepare_users(database, event_id, "user_a")
    store = FeedStore(database)
    store.list_feed("user_a", relation=None, item_status=None, cursor=None, limit=50)
    assert _watermark_ids(database, "user_a") == set()

    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "inc_delayed_delivered",
            [
                _update(
                    "upd_delayed_old_delivered",
                    "Investigating connectivity failures.",
                    "2026-08-22T00:00:00Z",
                    status="investigating",
                ),
                current,
            ],
        ),
        retrieved_at="2026-08-22T00:30:00Z",
    )
    LedgerProjector(database).project_event(event_id)
    new_items = projector.project_event_for_user(user_id="user_a", event_id=event_id)
    assert new_items


def test_correction_crosses_watermark_after_displayed_and_read(database) -> None:
    pipeline = StatuspagePipeline(database)
    first = pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "inc_correction_states",
            [
                _update(
                    "upd_correction_states",
                    "Requests from Europe are affected.",
                    "2026-08-22T00:00:00Z",
                )
            ],
        ),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    event_id = first.event_ids[0]
    projector = _prepare_users(database, event_id, "user_a")
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "user_a", relation=None, item_status=None, cursor=None, limit=50
    )
    store.record_exposures(
        "user_a",
        [{"delivery_id": item.delivery_id, "displayed_at": "2026-08-22T00:02:00Z"} for item in delivered],
    )
    store.mark_read("user_a", delivered[0].id)
    assert set(_states(database, "user_a").values()) == {"read"}

    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary(
            "inc_correction_states",
            [
                _update(
                    "upd_correction_states",
                    "Correction: the previous update was incorrect. Requests from Asia are affected.",
                    "2026-08-22T00:10:00Z",
                )
            ],
        ),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    LedgerProjector(database).project_event(event_id)
    new_for_a = projector.project_event_for_user(user_id="user_a", event_id=event_id)
    assert len(new_for_a) == 1
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
    assert projected["type"] == "correction"
    assert projected["claim_id"] not in _watermark_ids(database, "user_a")


def test_unknown_delivery_is_ignored_and_batch_is_capped(database) -> None:
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
    store = FeedStore(database)
    accepted = store.record_exposures(
        "user_a",
        [{"delivery_id": "dlv_unknown", "displayed_at": "2026-08-22T00:00:00Z"}],
    )
    assert accepted == 0
    try:
        ExposuresRequest.model_validate(
            {
                "items": [
                    {"delivery_id": f"dlv_{index}", "displayed_at": "2026-08-22T00:00:00Z"}
                    for index in range(51)
                ]
            }
        )
    except ValidationError:
        return
    raise AssertionError("batch larger than 50 must be rejected")
