from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.incident_ledger_store import IncidentLedgerStore


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
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                ],
            }
        ]
    }


def test_pipeline_ingests_summary_in_semantic_time_order(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )

    assert len(result.event_ids) == 1
    history = IncidentLedgerStore(database).history(result.event_ids[0])
    assert [state.status for state in history] == ["investigating", "identified"]


def test_replaying_same_summary_is_idempotent(database):
    pipeline = StatuspagePipeline(database)
    first = pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    second = pipeline.ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:20:00Z",
    )

    assert second.event_ids == first.event_ids
    assert len(IncidentLedgerStore(database).history(first.event_ids[0])) == 2
