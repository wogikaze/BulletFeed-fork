from datetime import datetime

from app.services.feed_projection import FeedProjector
from app.services.feedback_signals import assert_feedback_does_not_mutate_ledger, ledger_world_state
from app.services.follow_baseline import (
    SUBJECT_EVENT,
    SUBJECT_SOURCE,
    SUBJECT_TOPIC,
    claims_already_true_at,
    follow_iso,
    list_follow_checkpoints,
    ranking_knownness,
    record_follow_baseline,
)
from app.services.knowledge_evidence import (
    CONFIDENCE_HIGH,
    KIND_BASELINE,
    KIND_DISPLAYED,
    PROVENANCE_BASELINE,
    STATE_KNOWN,
    STATE_PROBABLY_KNOWN,
    STATE_UNKNOWN,
    append_knowledge_evidence,
    list_knowledge_evidence,
    presentation_for_item,
    replay_knowledge_state,
)
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.event_store import EventStore
from app.stores.feed_store import FeedStore
from app.stores.me_store import MeStore


def _ts(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _history_summary(*, incident_id: str = "inc_follow_baseline") -> dict:
    updates = []
    years = (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025)
    bodies = (
        "Investigating API latency.",
        "Identified database saturation.",
        "Monitoring recovery.",
        "Partial mitigation deployed.",
        "Identified remaining hot shard.",
        "Mitigation expanded.",
        "Service mostly recovered.",
        "Incident resolved for the year.",
    )
    statuses = (
        "investigating",
        "identified",
        "monitoring",
        "identified",
        "identified",
        "monitoring",
        "monitoring",
        "resolved",
    )
    for year, body, status in zip(years, bodies, statuses, strict=True):
        occurred = f"{year}-06-01T00:00:00Z"
        updates.append(
            {
                "id": f"upd_{incident_id}_{year}",
                "status": status,
                "body": body,
                "created_at": occurred,
                "updated_at": occurred,
                "display_at": occurred,
            }
        )
    return {
        "incidents": [
            {
                "id": incident_id,
                "name": "API latency",
                "impact": "major",
                "created_at": "2018-06-01T00:00:00Z",
                "shortlink": f"https://stspg.io/{incident_id}",
                "incident_updates": updates,
            }
        ]
    }


def _append_update(
    *,
    incident_id: str,
    update_id: str,
    body: str,
    occurred_at: str,
    status: str = "identified",
    explicit_correction: bool = False,
) -> dict:
    payload = {
        "id": update_id,
        "status": status,
        "body": body,
        "created_at": occurred_at,
        "updated_at": occurred_at,
        "display_at": occurred_at,
    }
    if explicit_correction:
        payload["body"] = f"Correction: {body}"
    return {
        "incidents": [
            {
                "id": incident_id,
                "name": "API latency",
                "impact": "major",
                "created_at": "2018-06-01T00:00:00Z",
                "shortlink": f"https://stspg.io/{incident_id}",
                "incident_updates": [payload],
            }
        ]
    }


def _ingest_history(database, *, user_id: str = "learner", page_id: str = "abcd1234") -> str:
    result = StatuspagePipeline(database).ingest_summary(
        page_id=page_id,
        summary=_history_summary(),
        retrieved_at="2025-06-01T00:01:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)",
            (user_id,),
        )
    FeedProjector(database).project_event_for_user(user_id=user_id, event_id=event_id)
    return event_id


def _ingest_later(
    database,
    *,
    event_id: str,
    user_id: str,
    occurred_at: str,
    body: str,
    update_id: str,
    explicit_correction: bool = False,
) -> None:
    StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_append_update(
            incident_id="inc_follow_baseline",
            update_id=update_id,
            body=body,
            occurred_at=occurred_at,
            explicit_correction=explicit_correction,
        ),
        retrieved_at=occurred_at,
    )
    LedgerProjector(database).project_event(event_id)
    FeedProjector(database).project_event_for_user(user_id=user_id, event_id=event_id)


def _feed_claim_states(database, user_id: str) -> list[tuple[str, str, str]]:
    store = FeedStore(database)
    items, _ = store.list_feed(
        user_id, relation=None, item_status=None, cursor=None, limit=50
    )
    rows: list[tuple[str, str, str]] = []
    with database.connect() as connection:
        for item in items:
            mapped = connection.execute(
                "SELECT claim_id FROM delta_claim_map WHERE delta_id = ?",
                (item.delta.id,),
            ).fetchone()
            claim_id = mapped["claim_id"] if mapped is not None else None
            state = ranking_knownness(connection, user_id=user_id, claim_id=claim_id)
            rows.append((item.delta.id, item.delta.occurred_at, state))
    return rows


def test_follow_event_does_not_flood_years_of_history(database) -> None:
    event_id = _ingest_history(database)
    followed_at = _ts("2026-01-01T00:00:00Z")
    EventStore(database).set_following(
        "learner", event_id, True, followed_at=followed_at
    )

    with database.connect() as connection:
        historical = claims_already_true_at(
            connection, event_ids=(event_id,), as_of_iso=follow_iso(followed_at)
        )
        assert len(historical) >= 8
        for row in historical:
            derived = replay_knowledge_state(
                connection, user_id="learner", claim_id=row["claim_id"]
            )
            assert derived.state == STATE_KNOWN
            assert derived.confidence == CONFIDENCE_HIGH
        evidence = [
            row
            for row in list_knowledge_evidence(connection, user_id="learner")
            if row.kind == KIND_BASELINE and row.claim_id
        ]
        assert evidence
        assert {row.provenance for row in evidence} == {PROVENANCE_BASELINE}
        checkpoints = list_follow_checkpoints(
            connection, user_id="learner", subject_kind=SUBJECT_EVENT, subject_id=event_id
        )
        assert checkpoints
        assert checkpoints[0].followed_at == followed_at
        assert checkpoints[0].catch_up is False

    states = _feed_claim_states(database, "learner")
    assert states
    assert all(state == STATE_KNOWN for _, _, state in states)


def test_new_delta_after_follow_still_surfaces(database) -> None:
    event_id = _ingest_history(database)
    followed_at = _ts("2026-01-01T00:00:00Z")
    EventStore(database).set_following(
        "learner", event_id, True, followed_at=followed_at
    )
    _ingest_later(
        database,
        event_id=event_id,
        user_id="learner",
        occurred_at="2026-06-01T00:00:00Z",
        body="New outage after tracking began.",
        update_id="upd_after_follow",
    )

    states = _feed_claim_states(database, "learner")
    unknown = [row for row in states if row[2] == STATE_UNKNOWN]
    known = [row for row in states if row[2] == STATE_KNOWN]
    assert unknown
    assert known
    assert unknown[0][1] == "2026-06-01T00:00:00Z"
    assert states[0][2] == STATE_UNKNOWN
    assert states[0][1] == "2026-06-01T00:00:00Z"


def test_catch_up_mode_is_explicit_and_keeps_history_unknown(database) -> None:
    event_id = _ingest_history(database)
    followed_at = _ts("2026-01-01T00:00:00Z")
    EventStore(database).set_following(
        "learner", event_id, True, catch_up=True, followed_at=followed_at
    )

    with database.connect() as connection:
        checkpoints = list_follow_checkpoints(
            connection, user_id="learner", subject_kind=SUBJECT_EVENT, subject_id=event_id
        )
        assert checkpoints[0].catch_up is True
        historical = claims_already_true_at(
            connection, event_ids=(event_id,), as_of_iso=follow_iso(followed_at)
        )
        for row in historical:
            derived = replay_knowledge_state(
                connection, user_id="learner", claim_id=row["claim_id"]
            )
            assert derived.state == STATE_UNKNOWN

    states = _feed_claim_states(database, "learner")
    assert states
    assert all(state == STATE_UNKNOWN for _, _, state in states)


def test_correction_after_baseline_still_surfaces(database) -> None:
    event_id = _ingest_history(database)
    followed_at = _ts("2026-01-01T00:00:00Z")
    EventStore(database).set_following(
        "learner", event_id, True, followed_at=followed_at
    )
    _ingest_later(
        database,
        event_id=event_id,
        user_id="learner",
        occurred_at="2026-06-02T00:00:00Z",
        body="the previous resolved state was wrong. Asia is still affected.",
        update_id="upd_correction_after_baseline",
        explicit_correction=True,
    )

    store = FeedStore(database)
    items, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    assert items
    assert items[0].delta.occurred_at == "2026-06-02T00:00:00Z"
    assert items[0].delta.type == "correction"
    with database.connect() as connection:
        claim_id = connection.execute(
            "SELECT claim_id FROM delta_claim_map WHERE delta_id = ?",
            (items[0].delta.id,),
        ).fetchone()["claim_id"]
        assert (
            replay_knowledge_state(connection, user_id="learner", claim_id=claim_id).state
            == STATE_UNKNOWN
        )


def test_unfollow_does_not_rewrite_ledger_or_delete_baseline(database) -> None:
    event_id = _ingest_history(database)
    store = EventStore(database)
    followed_at = _ts("2026-01-01T00:00:00Z")
    store.set_following("learner", event_id, True, followed_at=followed_at)
    with database.connect() as connection:
        before_ledger = ledger_world_state(connection)
        before_evidence = [
            (row.source_id, row.kind, row.claim_id, row.created_at)
            for row in list_knowledge_evidence(connection, user_id="learner")
            if row.kind == KIND_BASELINE
        ]
        assert before_evidence

    store.set_following("learner", event_id, False)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(before_ledger, ledger_world_state(connection))
        after_evidence = [
            (row.source_id, row.kind, row.claim_id, row.created_at)
            for row in list_knowledge_evidence(connection, user_id="learner")
            if row.kind == KIND_BASELINE
        ]
        assert after_evidence == before_evidence
        follow = connection.execute(
            "SELECT following FROM event_follows WHERE user_id = ? AND event_id = ?",
            ("learner", event_id),
        ).fetchone()
        assert follow["following"] == 0


def test_refollow_is_start_from_now_and_keeps_prior_evidence(database) -> None:
    event_id = _ingest_history(database)
    store = EventStore(database)
    first = _ts("2026-01-01T00:00:00Z")
    store.set_following("learner", event_id, True, followed_at=first)
    store.set_following("learner", event_id, False)
    _ingest_later(
        database,
        event_id=event_id,
        user_id="learner",
        occurred_at="2026-03-01T00:00:00Z",
        body="Incident while unfollowed.",
        update_id="upd_while_unfollowed",
    )
    second = _ts("2026-04-01T00:00:00Z")
    store.set_following("learner", event_id, True, followed_at=second)
    _ingest_later(
        database,
        event_id=event_id,
        user_id="learner",
        occurred_at="2026-06-01T00:00:00Z",
        body="Incident after refollow.",
        update_id="upd_after_refollow",
    )

    with database.connect() as connection:
        checkpoints = list_follow_checkpoints(
            connection, user_id="learner", subject_kind=SUBJECT_EVENT, subject_id=event_id
        )
        assert [item.followed_at for item in checkpoints] == [first, second]
        gap_claim = connection.execute(
            """
            SELECT m.claim_id
            FROM deltas d
            JOIN delta_claim_map m ON m.delta_id = d.id
            WHERE d.event_id = ? AND d.occurred_at = '2026-03-01T00:00:00Z'
            """,
            (event_id,),
        ).fetchone()["claim_id"]
        after_claim = connection.execute(
            """
            SELECT m.claim_id
            FROM deltas d
            JOIN delta_claim_map m ON m.delta_id = d.id
            WHERE d.event_id = ? AND d.occurred_at = '2026-06-01T00:00:00Z'
            """,
            (event_id,),
        ).fetchone()["claim_id"]
        assert (
            replay_knowledge_state(connection, user_id="learner", claim_id=gap_claim).state
            == STATE_KNOWN
        )
        assert (
            replay_knowledge_state(connection, user_id="learner", claim_id=after_claim).state
            == STATE_UNKNOWN
        )


def test_topic_follow_baselines_matching_history(database) -> None:
    _ingest_history(database)
    followed_at = _ts("2026-01-01T00:00:00Z")
    MeStore(database).add_topic(
        "learner", "API", "technology", reproject=True, catch_up=False
    )
    with database.connect() as connection:
        record_follow_baseline(
            connection,
            user_id="learner",
            subject_kind=SUBJECT_TOPIC,
            subject_id="topic_api_test",
            followed_at=followed_at,
            topic_name="API",
        )
        historical = [
            row
            for row in list_knowledge_evidence(connection, user_id="learner")
            if row.kind == KIND_BASELINE and row.claim_id
        ]
        assert historical
        assert all(
            replay_knowledge_state(connection, user_id="learner", claim_id=row.claim_id).state
            == STATE_KNOWN
            for row in historical
        )


def test_source_follow_baselines_matching_history(database) -> None:
    event_id = _ingest_history(database)
    followed_at = _ts("2026-01-01T00:00:00Z")
    with database.connect() as connection:
        result = record_follow_baseline(
            connection,
            user_id="learner",
            subject_kind=SUBJECT_SOURCE,
            subject_id="statuspage:abcd1234",
            followed_at=followed_at,
            source_type="statuspage",
            source_key="abcd1234",
        )
        assert result.claim_ids
        for claim_id in result.claim_ids:
            assert (
                replay_knowledge_state(connection, user_id="learner", claim_id=claim_id).state
                == STATE_KNOWN
            )
        assert event_id


def test_baseline_is_replayable_and_does_not_pretend_read(database) -> None:
    event_id = _ingest_history(database)
    followed_at = _ts("2026-01-01T00:00:00Z")
    EventStore(database).set_following(
        "learner", event_id, True, followed_at=followed_at
    )
    with database.connect() as connection:
        kinds = {row.kind for row in list_knowledge_evidence(connection, user_id="learner")}
        assert KIND_BASELINE in kinds
        assert "read" not in kinds
        replayed = list_follow_checkpoints(connection, user_id="learner")
        assert replayed[0].followed_at == followed_at
        first_claim = replayed[0].claim_ids[0]
        derived = replay_knowledge_state(
            connection, user_id="learner", claim_id=first_claim
        )
        assert derived.state == STATE_KNOWN
        assert derived.visibility == "hide"


def test_uncertain_knownness_is_not_hard_hidden(database) -> None:
    event_id = _ingest_history(database)
    with database.connect() as connection:
        claim_id = connection.execute(
            """
            SELECT m.claim_id
            FROM deltas d
            JOIN delta_claim_map m ON m.delta_id = d.id
            WHERE d.event_id = ?
            ORDER BY d.occurred_at DESC, d.id DESC
            LIMIT 1
            """,
            (event_id,),
        ).fetchone()["claim_id"]
        append_knowledge_evidence(
            connection,
            user_id="learner",
            kind=KIND_DISPLAYED,
            source_id="dlv_uncertain",
            claim_id=claim_id,
            event_id=event_id,
            created_at=_ts("2026-01-01T00:00:00Z"),
        )
        derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
        assert derived.state == STATE_PROBABLY_KNOWN
        assert derived.visibility == "demote"
        assert (
            presentation_for_item(
                state=derived.state,
                confidence=derived.confidence,
                importance_level="critical",
            )
            != "hide"
        )

    states = _feed_claim_states(database, "learner")
    assert any(state == STATE_PROBABLY_KNOWN for _, _, state in states)
    assert any(state == STATE_UNKNOWN for _, _, state in states)
