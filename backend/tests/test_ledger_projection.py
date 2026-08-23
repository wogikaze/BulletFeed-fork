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


def test_projector_derives_public_event_delta_timeline_and_sources(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]

    LedgerProjector(database).project_event(event_id)

    with database.connect() as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        deltas = connection.execute(
            "SELECT * FROM deltas WHERE event_id = ? ORDER BY occurred_at",
            (event_id,),
        ).fetchall()
        timeline = connection.execute(
            "SELECT * FROM event_timeline WHERE event_id = ? ORDER BY occurred_at",
            (event_id,),
        ).fetchall()
        sources = connection.execute(
            "SELECT * FROM event_sources WHERE event_id = ? ORDER BY published_at",
            (event_id,),
        ).fetchall()

    assert event["current_phase"] == "identified"
    assert [row["type"] for row in deltas] == ["new_fact", "state_update"]
    assert deltas[1]["before_text"] == "investigating"
    assert deltas[1]["after_text"] == "identified"
    assert len(timeline) == 2
    assert [row["evidence"] for row in sources] == [
        "Investigating elevated latency.",
        "Database saturation identified.",
    ]


def test_projecting_same_event_twice_is_idempotent(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    projector = LedgerProjector(database)
    projector.project_event(result.event_ids[0])
    projector.project_event(result.event_ids[0])

    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM deltas WHERE event_id = ?",
            (result.event_ids[0],),
        ).fetchone()["count"]
    assert count == 2
