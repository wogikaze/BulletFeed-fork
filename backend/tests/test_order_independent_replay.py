from app.database import Database
from app.services.statuspage_incidents import StatuspageIncidentObservation
from app.stores.incident_ledger_store import IncidentLedgerStore


def _update(update_id: str, status: str, at: str) -> StatuspageIncidentObservation:
    body = f"Incident is {status}."
    return StatuspageIncidentObservation(
        page_id="abcd1234",
        incident_id="inc_replay",
        update_id=update_id,
        incident_name="API latency",
        status=status,
        body=body,
        impact="major",
        published_at=at,
        updated_at=at,
        original_url="https://stspg.io/inc_replay",
        raw={"update": {"id": update_id, "status": status, "body": body, "display_at": at}},
    )


def _history(database: Database, sequence: list[StatuspageIncidentObservation]):
    store = IncidentLedgerStore(database)
    event_id = ""
    for index, item in enumerate(sequence):
        state = store.ingest(item, retrieved_at=f"2026-08-22T01:0{index}:00Z")
        event_id = state.event_id
    return [
        (state.status, state.valid_at, state.relation_type)
        for state in store.history(event_id)
    ]


def test_final_ledger_is_independent_of_arrival_order(tmp_path):
    investigating = _update("upd_1", "investigating", "2026-08-22T00:00:00Z")
    identified = _update("upd_2", "identified", "2026-08-22T00:10:00Z")
    resolved = _update("upd_3", "resolved", "2026-08-22T00:20:00Z")

    ordered = Database(tmp_path / "ordered.db")
    ordered.initialize()
    delayed = Database(tmp_path / "delayed.db")
    delayed.initialize()

    ordered_history = _history(ordered, [investigating, identified, resolved])
    delayed_history = _history(delayed, [resolved, investigating, identified])

    assert delayed_history == ordered_history
    assert ordered_history == [
        ("investigating", "2026-08-22T00:00:00Z", "NEW_FACT"),
        ("identified", "2026-08-22T00:10:00Z", "STATE_UPDATE"),
        ("resolved", "2026-08-22T00:20:00Z", "STATE_UPDATE"),
    ]
