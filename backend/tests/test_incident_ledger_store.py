from app.services.statuspage_incidents import StatuspageIncidentObservation
from app.stores.incident_ledger_store import IncidentLedgerStore


def _item(update_id: str, status: str, body: str, published_at: str):
    incident = {"id": "inc_1", "name": "API latency", "impact": "major"}
    update = {"id": update_id, "status": status, "body": body, "display_at": published_at}
    return StatuspageIncidentObservation(
        page_id="abcd1234",
        incident_id="inc_1",
        update_id=update_id,
        incident_name="API latency",
        status=status,
        body=body,
        impact="major",
        published_at=published_at,
        updated_at=published_at,
        original_url="https://stspg.io/inc_1",
        raw={"incident": incident, "update": update},
    )


def test_same_incident_updates_share_event_and_preserve_state_history(database):
    store = IncidentLedgerStore(database)
    investigating = store.ingest(
        _item("upd_1", "investigating", "Investigating latency.", "2026-08-22T00:00:00Z"),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    identified = store.ingest(
        _item("upd_2", "identified", "Database saturation identified.", "2026-08-22T00:10:00Z"),
        retrieved_at="2026-08-22T00:11:00Z",
    )

    assert identified.event_id == investigating.event_id
    history = store.history(investigating.event_id)
    assert [state.status for state in history] == ["investigating", "identified"]
    assert [state.relation_type for state in history] == ["NEW_FACT", "STATE_UPDATE"]


def test_retry_does_not_duplicate_claim_or_relation(database):
    store = IncidentLedgerStore(database)
    item = _item("upd_1", "investigating", "Investigating latency.", "2026-08-22T00:00:00Z")

    first = store.ingest(item, retrieved_at="2026-08-22T00:01:00Z")
    retried = store.ingest(item, retrieved_at="2026-08-22T00:02:00Z")

    assert retried.claim_id == first.claim_id
    assert len(store.history(first.event_id)) == 1


def test_same_status_with_new_detail_is_detail_not_state_update(database):
    store = IncidentLedgerStore(database)
    first = store.ingest(
        _item("upd_1", "identified", "Issue identified.", "2026-08-22T00:00:00Z"),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    store.ingest(
        _item("upd_2", "identified", "Database saturation identified.", "2026-08-22T00:05:00Z"),
        retrieved_at="2026-08-22T00:06:00Z",
    )

    assert [state.relation_type for state in store.history(first.event_id)] == ["NEW_FACT", "DETAIL"]
