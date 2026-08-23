from app.stores.observation_store import ObservationStore


def test_append_is_idempotent_for_same_source_payload(database):
    store = ObservationStore(database)
    payload = {"id": "inc_1", "status": "investigating", "name": "API incident"}

    first = store.append(
        source_type="statuspage",
        source_key="example",
        source_observation_id="inc_1",
        payload=payload,
        original_url="https://example.statuspage.io/incidents/inc_1",
        published_at="2026-08-22T00:00:00Z",
        retrieved_at="2026-08-22T00:01:00Z",
    )
    retried = store.append(
        source_type="statuspage",
        source_key="example",
        source_observation_id="inc_1",
        payload=payload,
        original_url="https://example.statuspage.io/incidents/inc_1",
        published_at="2026-08-22T00:00:00Z",
        retrieved_at="2026-08-22T00:02:00Z",
    )

    assert retried.id == first.id
    assert len(
        store.list_for_source_observation(
            source_type="statuspage",
            source_key="example",
            source_observation_id="inc_1",
        )
    ) == 1


def test_changed_payload_appends_new_observation_without_overwriting_history(database):
    store = ObservationStore(database)
    common = dict(
        source_type="statuspage",
        source_key="example",
        source_observation_id="inc_1",
        original_url="https://example.statuspage.io/incidents/inc_1",
        published_at="2026-08-22T00:00:00Z",
    )

    investigating = store.append(
        **common,
        payload={"id": "inc_1", "status": "investigating"},
        retrieved_at="2026-08-22T00:01:00Z",
    )
    identified = store.append(
        **common,
        payload={"id": "inc_1", "status": "identified"},
        retrieved_at="2026-08-22T00:03:00Z",
    )

    observations = store.list_for_source_observation(
        source_type="statuspage",
        source_key="example",
        source_observation_id="inc_1",
    )
    assert [item.id for item in observations] == [investigating.id, identified.id]
    assert [item.payload["status"] for item in observations] == ["investigating", "identified"]
