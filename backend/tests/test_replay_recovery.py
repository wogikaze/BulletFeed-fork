import pytest

from app.database import Database
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_incidents import normalize_incident_updates
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.incident_ledger_store import IncidentLedgerStore


def _summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_recovery",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_recovery",
                "incident_updates": [
                    {
                        "id": "upd_recovery_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "display_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_recovery_2",
                        "status": "resolved",
                        "body": "Service recovered.",
                        "display_at": "2026-08-22T00:20:00Z",
                        "updated_at": "2026-08-22T00:20:00Z",
                    },
                ],
            }
        ]
    }


def _projection_snapshot(database: Database, event_id: str) -> tuple:
    with database.connect() as connection:
        event = connection.execute(
            """
            SELECT id, title, summary, current_phase, current_summary,
                   current_since, current_confidence, updated_at
            FROM events WHERE id = ?
            """,
            (event_id,),
        ).fetchone()
        deltas = connection.execute(
            """
            SELECT id, type, summary, before_text, after_text, occurred_at
            FROM deltas WHERE event_id = ? ORDER BY id
            """,
            (event_id,),
        ).fetchall()
        timeline = connection.execute(
            """
            SELECT id, delta_id, type, occurred_at, title, description,
                   state_before, state_after
            FROM event_timeline WHERE event_id = ? ORDER BY id
            """,
            (event_id,),
        ).fetchall()
        sources = connection.execute(
            """
            SELECT id, publisher, kind, title, url, published_at, retrieved_at, evidence
            FROM event_sources WHERE event_id = ? ORDER BY id
            """,
            (event_id,),
        ).fetchall()
    assert event is not None
    return (
        tuple(event),
        tuple(tuple(row) for row in deltas),
        tuple(tuple(row) for row in timeline),
        tuple(tuple(row) for row in sources),
    )


def test_retry_recovers_when_observation_commits_before_claim_transaction_fails(
    database: Database,
    monkeypatch,
) -> None:
    item = normalize_incident_updates("abcd1234", _summary())[0]
    store = IncidentLedgerStore(database)

    def fail_rebuild(connection, event_id):
        del connection, event_id
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(store, "_rebuild_relations", fail_rebuild)
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.ingest(item, retrieved_at="2026-08-22T00:01:00Z")

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0] == 0

    recovered = IncidentLedgerStore(database).ingest(
        item,
        retrieved_at="2026-08-22T00:02:00Z",
    )
    assert recovered.relation_type == "NEW_FACT"
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM claim_relations").fetchone()[0] == 1


def test_restart_between_ingest_and_projection_is_replayable(tmp_path) -> None:
    path = tmp_path / "replay.db"
    first_process = Database(path)
    first_process.initialize()
    first_result = StatuspagePipeline(first_process).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:21:00Z",
    )
    event_id = first_result.event_ids[0]

    restarted = Database(path)
    restarted.initialize()
    StatuspagePipeline(restarted).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:22:00Z",
    )
    LedgerProjector(restarted).project_event(event_id)
    first_snapshot = _projection_snapshot(restarted, event_id)

    second_restart = Database(path)
    second_restart.initialize()
    StatuspagePipeline(second_restart).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:23:00Z",
    )
    LedgerProjector(second_restart).project_event(event_id)
    second_snapshot = _projection_snapshot(second_restart, event_id)

    assert second_snapshot == first_snapshot
    with second_restart.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM claim_relations").fetchone()[0] == 2
