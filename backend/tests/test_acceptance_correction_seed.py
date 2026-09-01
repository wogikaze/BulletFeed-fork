from app.routers.acceptance_harness import _statuspage_correction_summary
from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_incidents import normalize_incident_updates
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def test_harness_correction_summary_is_explicit() -> None:
    items = normalize_incident_updates("abcd1234", _statuspage_correction_summary())
    assert len(items) == 1
    assert items[0].explicit_correction is True
    assert items[0].incident_id == "inc_android_acceptance"


def test_correction_after_already_knew_still_projects_correction_delta(database) -> None:
    pipeline = StatuspagePipeline(database)
    first = pipeline.ingest_summary(
        page_id="abcd1234",
        summary={
            "incidents": [
                {
                    "id": "inc_android_acceptance",
                    "name": "API latency",
                    "impact": "major",
                    "created_at": "2026-08-22T00:00:00Z",
                    "shortlink": "https://stspg.io/inc_android_acceptance",
                    "incident_updates": [
                        {
                            "id": "upd_android_acceptance_1",
                            "status": "investigating",
                            "body": "Investigating elevated latency.",
                            "created_at": "2026-08-22T00:00:00Z",
                            "updated_at": "2026-08-22T00:00:00Z",
                            "display_at": "2026-08-22T00:00:00Z",
                        }
                    ],
                }
            ]
        },
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = first.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_corr_android', 0)")
    projector = FeedProjector(database)
    cards = projector.project_event_for_user(user_id="user_corr_android", event_id=event_id)
    assert cards
    store = FeedStore(database)
    store.save_feedback("user_corr_android", cards[0], "already_knew")
    second = pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_correction_summary(),
        retrieved_at="2026-08-22T00:21:00Z",
    )
    assert second.event_ids == first.event_ids
    assert second.claims[0].relation_type == "CORRECTION"
    LedgerProjector(database).project_event(event_id)
    projector.project_event_for_user(user_id="user_corr_android", event_id=event_id)
    after, _ = store.list_feed(
        "user_corr_android",
        relation=None,
        item_status=None,
        cursor=None,
        limit=50,
    )
    assert any(item.delta.type == "correction" for item in after)
