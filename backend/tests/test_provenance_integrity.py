from app.evaluation.provenance import audit_displayed_provenance
from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline


def _summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_provenance",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_provenance",
                "incident_updates": [
                    {
                        "id": "upd_provenance",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "display_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def test_feed_claim_has_complete_machine_checkable_provenance_chain(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_provenance', 0)")
    FeedProjector(database).project_event_for_user(
        user_id="user_provenance",
        event_id=event_id,
    )

    report = audit_displayed_provenance(database)
    assert report.displayed_claim_count == 1
    assert report.complete_chain_count == 1
    assert report.broken_chain_count == 0
    assert report.coverage == 1.0

    with database.connect() as connection:
        connection.execute("DELETE FROM event_source_claim_map")

    broken = audit_displayed_provenance(database)
    assert broken.complete_chain_count == 0
    assert broken.broken_chain_count == 1
    assert broken.coverage == 0.0
