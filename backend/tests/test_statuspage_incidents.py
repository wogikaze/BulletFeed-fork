from app.services.statuspage_incidents import normalize_incident_updates


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
                        "id": "upd_2",
                        "status": "identified",
                        "body": "Database saturation identified.",
                        "created_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:10:00Z",
                        "display_at": "2026-08-22T00:10:00Z",
                    },
                    {
                        "id": "upd_1",
                        "status": "investigating",
                        "body": "We are investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                ],
            }
        ]
    }


def test_normalization_returns_chronological_incident_updates():
    items = normalize_incident_updates("abcd1234", _summary())

    assert [item.update_id for item in items] == ["upd_1", "upd_2"]
    assert [item.status for item in items] == ["investigating", "identified"]
    assert items[0].event_key == "statuspage:abcd1234:inc_1"
    assert items[0].original_url == "https://stspg.io/inc_1"
    assert items[0].body == "We are investigating elevated latency."


def test_normalization_keeps_each_update_raw_payload_for_provenance():
    item = normalize_incident_updates("abcd1234", _summary())[0]

    assert item.raw["incident"]["id"] == "inc_1"
    assert item.raw["update"]["id"] == "upd_1"
