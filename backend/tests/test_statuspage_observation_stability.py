from app.services.statuspage_pipeline import StatuspagePipeline


def _update(update_id: str, status: str, at: str) -> dict:
    return {
        "id": update_id,
        "status": status,
        "body": f"Incident is {status}.",
        "created_at": at,
        "updated_at": at,
        "display_at": at,
    }


def _summary(updates: list[dict]) -> dict:
    return {
        "incidents": [
            {
                "id": "inc_stable",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "updated_at": updates[-1]["updated_at"],
                "status": updates[-1]["status"],
                "shortlink": "https://stspg.io/inc_stable",
                "incident_updates": updates,
            }
        ]
    }


def test_old_statuspage_update_does_not_change_identity_when_new_sibling_arrives(database):
    first = _update("upd_1", "investigating", "2026-08-22T00:00:00Z")
    second = _update("upd_2", "identified", "2026-08-22T00:10:00Z")
    pipeline = StatuspagePipeline(database)

    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary([first]),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary([first, second]),
        retrieved_at="2026-08-22T00:11:00Z",
    )

    with database.connect() as connection:
        observation_count = connection.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE source_type = 'statuspage'"
        ).fetchone()["count"]
        claim_count = connection.execute(
            "SELECT COUNT(*) AS count FROM state_claims"
        ).fetchone()["count"]
        relation_count = connection.execute(
            "SELECT COUNT(*) AS count FROM claim_relations"
        ).fetchone()["count"]

    assert observation_count == 2
    assert claim_count == 2
    assert relation_count == 2
