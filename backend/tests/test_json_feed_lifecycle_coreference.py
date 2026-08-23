from app.services.json_feed_pipeline import ingest_json_feed_events


def test_json_feed_explicit_retirement_forms_one_event(database) -> None:
    feed = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "Vendor Changelog",
        "feed_url": "https://updates.example.com/feed.json",
        "items": [
            {
                "id": "models-retirement-announced",
                "url": "https://updates.example.com/models-retirement-announced",
                "title": "Example Models is being fully retired on September 1, 2026",
                "summary": "The service will retire on September 1.",
                "date_published": "2026-08-01T00:00:00Z",
                "date_modified": "2026-08-01T00:00:00Z",
            },
            {
                "id": "models-retired",
                "url": "https://updates.example.com/models-retired",
                "title": "Example Models is now retired",
                "summary": "The service is retired.",
                "date_published": "2026-09-01T00:00:00Z",
                "date_modified": "2026-09-01T00:00:00Z",
            },
        ],
    }

    result = ingest_json_feed_events(
        database,
        feed=feed,
        feed_url="https://updates.example.com/feed.json",
        retrieved_at="2026-09-01T00:05:00Z",
    )

    assert len(result.claim_ids) == 2
    assert len(result.event_ids) == 1
    with database.connect() as connection:
        event = connection.execute(
            "SELECT current_phase FROM events WHERE id = ?",
            (result.event_ids[0],),
        ).fetchone()
        relations = connection.execute(
            "SELECT relation_type FROM claim_relations WHERE event_id = ? ORDER BY occurred_at, id",
            (result.event_ids[0],),
        ).fetchall()

    assert event["current_phase"] == "retired"
    assert [row["relation_type"] for row in relations] == ["NEW_FACT", "STATE_UPDATE"]
