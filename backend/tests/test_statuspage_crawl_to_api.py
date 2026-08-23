from app.config import get_settings
from app.services import statuspage
from app.services.feed_projection import FeedProjector
from app.services.statuspage_crawler import StatuspageCrawler


async def test_statuspage_fixture_reaches_existing_feed_and_event_apis(client, database, monkeypatch):
    async def fake_summary(settings, page_id):
        del settings
        assert page_id == "abcd1234"
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

    monkeypatch.setattr(statuspage, "get_summary", fake_summary)

    session = client.post("/v1/sessions")
    assert session.status_code == 200
    session_body = session.json()
    headers = {"Authorization": f"Bearer {session_body['accessToken']}"}

    result = await StatuspageCrawler(database, get_settings()).crawl_page("abcd1234")
    event_id = result.event_ids[0]
    FeedProjector(database).project_event_for_user(
        user_id=session_body["userId"],
        event_id=event_id,
    )

    feed_response = client.get("/v1/feed", headers=headers)
    assert feed_response.status_code == 200
    item = next(item for item in feed_response.json()["items"] if item["eventId"] == event_id)
    assert item["delta"]["type"] in {"new_fact", "state_update"}

    detail_response = client.get(
        f"/v1/events/{event_id}",
        headers=headers,
        params={"fromFeedItem": item["id"]},
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["currentState"]["phase"] == "identified"
    assert detail["latestDelta"]["after"] == "identified"
    assert [entry["state"]["after"] for entry in detail["timeline"]] == [
        "investigating",
        "identified",
    ]
    assert [source["evidence"] for source in detail["sources"]] == [
        "Investigating elevated latency.",
        "Database saturation identified.",
    ]
