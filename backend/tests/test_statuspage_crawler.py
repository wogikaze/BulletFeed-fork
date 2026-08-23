from app.config import get_settings
from app.services import statuspage
from app.services.statuspage_crawler import StatuspageCrawler


async def test_crawl_page_runs_http_payload_through_ledger_and_projection(database, monkeypatch):
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
    result = await StatuspageCrawler(database, get_settings()).crawl_page("abcd1234")

    assert len(result.event_ids) == 1
    with database.connect() as connection:
        event = connection.execute(
            "SELECT * FROM events WHERE id = ?",
            (result.event_ids[0],),
        ).fetchone()
        deltas = connection.execute(
            "SELECT type FROM deltas WHERE event_id = ? ORDER BY occurred_at",
            (result.event_ids[0],),
        ).fetchall()
    assert event["current_phase"] == "identified"
    assert [row["type"] for row in deltas] == ["new_fact", "state_update"]
