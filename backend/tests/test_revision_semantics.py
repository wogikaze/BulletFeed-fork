from app.services.statuspage_incidents import normalize_incident_updates
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.incident_ledger_store import IncidentLedgerStore


def _summary():
    return {
        "incidents": [
            {
                "id": "inc_revision",
                "name": "API routing issue",
                "impact": "major",
                "created_at": "2026-08-22T00:10:00Z",
                "shortlink": "https://stspg.io/inc_revision",
                "incident_updates": [
                    {
                        "id": "upd_original",
                        "status": "identified",
                        "body": "Database saturation identified.",
                        "display_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:10:00Z",
                    },
                    {
                        "id": "upd_conflict",
                        "status": "investigating",
                        "body": "Network path suspected.",
                        "display_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:11:00Z",
                    },
                    {
                        "id": "upd_correction",
                        "status": "identified",
                        "body": (
                            "Correction: the network-path update was incorrect; "
                            "database saturation is the cause."
                        ),
                        "display_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:12:00Z",
                    },
                ],
            }
        ]
    }


def test_statuspage_revision_cues_produce_conflict_and_correction(database):
    normalized = normalize_incident_updates("abcd1234", _summary())
    assert [item.update_id for item in normalized] == [
        "upd_original",
        "upd_conflict",
        "upd_correction",
    ]
    assert normalized[-1].explicit_correction is True

    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:13:00Z",
    )
    history = IncidentLedgerStore(database).history(result.event_ids[0])

    assert [state.relation_type for state in history] == [
        "NEW_FACT",
        "UNRESOLVED_CONTRADICTION",
        "CORRECTION",
    ]
