from datetime import datetime

from fastapi.testclient import TestClient

from app.database import Database
from app.services.false_suppression import decide_suppression
from app.services.feed_projection import FeedProjector
from app.services.feedback_signals import assert_feedback_does_not_mutate_ledger, ledger_world_state
from app.services.follow_baseline import claims_already_true_at, follow_iso
from app.services.knowledge_bootstrap import (
    POLICY_VERSION,
    BootstrapEvalCase,
    evaluate_bootstrap_impact,
    inspect_bootstrap,
    ranking_knownness,
    record_current_state_checkpoint,
    record_explicit_bootstrap,
    record_inferred_bootstrap,
    reset_bootstrap_knowledge,
)
from app.services.knowledge_evidence import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    KIND_ALREADY_KNEW,
    KIND_BASELINE,
    KIND_BOOTSTRAP_CLAIM,
    KIND_BOOTSTRAP_EXPLICIT,
    KIND_BOOTSTRAP_INFERRED,
    KIND_DISPLAYED,
    PROVENANCE_BOOTSTRAP,
    PROVENANCE_BOOTSTRAP_INFERRED,
    STATE_KNOWN,
    STATE_PROBABLY_KNOWN,
    STATE_UNKNOWN,
    KnowledgeEvidence,
    append_knowledge_evidence,
    list_knowledge_evidence,
    may_hide,
    replay_knowledge_state,
)
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def _ts(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _history_summary(*, incident_id: str = "inc_knowledge_bootstrap") -> dict:
    updates = []
    years = (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025)
    for year in years:
        occurred = f"{year}-06-01T00:00:00Z"
        updates.append(
            {
                "id": f"upd_{incident_id}_{year}",
                "status": "identified",
                "body": f"Identified remaining issue in {year}.",
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


def _append_update(*, occurred_at: str, body: str, update_id: str) -> dict:
    return {
        "incidents": [
            {
                "id": "inc_knowledge_bootstrap",
                "name": "API latency",
                "impact": "major",
                "created_at": "2018-06-01T00:00:00Z",
                "shortlink": "https://stspg.io/inc_knowledge_bootstrap",
                "incident_updates": [
                    {
                        "id": update_id,
                        "status": "identified",
                        "body": body,
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                        "display_at": occurred_at,
                    }
                ],
            }
        ]
    }


def _ingest_history(database: Database, *, user_id: str) -> str:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
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


def _ingest_later(database: Database, *, event_id: str, user_id: str, occurred_at: str) -> None:
    StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_append_update(
            occurred_at=occurred_at,
            body="New outage after the current-state checkpoint.",
            update_id=f"upd_after_{occurred_at[:4]}",
        ),
        retrieved_at=occurred_at,
    )
    LedgerProjector(database).project_event(event_id)
    FeedProjector(database).project_event_for_user(user_id=user_id, event_id=event_id)


def _claim_ids(database: Database, event_id: str, *, as_of: str) -> list[str]:
    with database.connect() as connection:
        rows = claims_already_true_at(connection, event_ids=(event_id,), as_of_iso=as_of)
    return [str(row["claim_id"]) for row in rows]


def test_empty_bootstrap_is_inspectable(database: Database) -> None:
    _ingest_history(database, user_id="learner")
    with database.connect() as connection:
        summary = inspect_bootstrap(connection, user_id="learner")
    assert summary.explicit_claim_ids == ()
    assert summary.inferred_claim_ids == ()
    assert summary.checkpoints == ()
    assert summary.evidence == ()


def test_explicit_already_known_facts_are_bootstrap_not_delivery(database: Database) -> None:
    event_id = _ingest_history(database, user_id="learner")
    claim_ids = _claim_ids(database, event_id, as_of="2025-06-01T00:00:00Z")
    assert claim_ids
    with database.connect() as connection:
        before = ledger_world_state(connection)
        session_id, recorded = record_explicit_bootstrap(
            connection,
            user_id="learner",
            claim_ids=claim_ids[:2],
            created_at=_ts("2026-01-01T00:00:00Z"),
        )
        after = ledger_world_state(connection)
        assert_feedback_does_not_mutate_ledger(before, after)
        derived = replay_knowledge_state(connection, user_id="learner", claim_id=recorded[0])
        assert derived.state == STATE_KNOWN
        assert derived.confidence == CONFIDENCE_HIGH
        rows = [
            row
            for row in list_knowledge_evidence(connection, user_id="learner")
            if row.claim_id == recorded[0]
        ]
        assert {row.kind for row in rows} == {KIND_BOOTSTRAP_EXPLICIT}
        assert {row.provenance for row in rows} == {PROVENANCE_BOOTSTRAP}
        assert session_id.startswith("kbs_")
        assert ranking_knownness(connection, user_id="learner", claim_id=recorded[0]) == STATE_KNOWN


def test_current_state_checkpoint_does_not_claim_later_intermediates(
    database: Database,
) -> None:
    event_id = _ingest_history(database, user_id="learner")
    as_of = _ts("2026-01-01T00:00:00Z")
    with database.connect() as connection:
        checkpoint = record_current_state_checkpoint(
            connection,
            user_id="learner",
            subject_kind="event",
            subject_id=event_id,
            as_of=as_of,
        )
        historical = claims_already_true_at(connection, event_ids=(event_id,), as_of_iso=follow_iso(as_of))
        assert checkpoint.claim_ids
        assert set(checkpoint.claim_ids) == {str(row["claim_id"]) for row in historical}
        for claim_id in checkpoint.claim_ids:
            derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
            assert derived.state == STATE_KNOWN

    _ingest_later(
        database,
        event_id=event_id,
        user_id="learner",
        occurred_at="2026-06-01T00:00:00Z",
    )
    with database.connect() as connection:
        later = [
            str(row["claim_id"])
            for row in claims_already_true_at(
                connection, event_ids=(event_id,), as_of_iso="2026-06-01T00:00:00Z"
            )
            if str(row["claim_id"]) not in set(checkpoint.claim_ids)
        ]
        assert later
        for claim_id in later:
            derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
            assert derived.state == STATE_UNKNOWN
        kinds = {row.kind for row in list_knowledge_evidence(connection, user_id="learner") if row.claim_id}
        assert KIND_BOOTSTRAP_CLAIM in kinds
        assert KIND_BASELINE not in kinds


def test_catch_up_checkpoint_records_timestamp_only(database: Database) -> None:
    event_id = _ingest_history(database, user_id="learner")
    with database.connect() as connection:
        checkpoint = record_current_state_checkpoint(
            connection,
            user_id="learner",
            subject_kind="event",
            subject_id=event_id,
            catch_up=True,
            as_of=_ts("2026-01-01T00:00:00Z"),
        )
        assert checkpoint.catch_up is True
        assert checkpoint.claim_ids == ()
        historical = claims_already_true_at(
            connection,
            event_ids=(event_id,),
            as_of_iso="2026-01-01T00:00:00Z",
        )
        assert historical
        for row in historical:
            derived = replay_knowledge_state(connection, user_id="learner", claim_id=row["claim_id"])
            assert derived.state == STATE_UNKNOWN


def test_reset_removes_bootstrap_only(database: Database) -> None:
    event_id = _ingest_history(database, user_id="learner")
    claim_ids = _claim_ids(database, event_id, as_of="2025-06-01T00:00:00Z")
    with database.connect() as connection:
        append_knowledge_evidence(
            connection,
            user_id="learner",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_keep",
            claim_id=claim_ids[0],
            event_id=event_id,
        )
        record_explicit_bootstrap(connection, user_id="learner", claim_ids=claim_ids[:1])
        before = ledger_world_state(connection)
        deleted = reset_bootstrap_knowledge(connection, user_id="learner")
        after = ledger_world_state(connection)
        assert deleted >= 1
        assert_feedback_does_not_mutate_ledger(before, after)
        remaining = list_knowledge_evidence(connection, user_id="learner")
        assert {row.kind for row in remaining} == {KIND_ALREADY_KNEW}
        summary = inspect_bootstrap(connection, user_id="learner")
        assert summary.evidence == ()
        assert (
            replay_knowledge_state(connection, user_id="learner", claim_id=claim_ids[0]).state == STATE_KNOWN
        )


def test_inferred_bootstrap_cannot_hard_hide(database: Database) -> None:
    event_id = _ingest_history(database, user_id="learner")
    claim_ids = _claim_ids(database, event_id, as_of="2025-06-01T00:00:00Z")
    with database.connect() as connection:
        record_inferred_bootstrap(connection, user_id="learner", claim_id=claim_ids[0])
        derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_ids[0])
        assert derived.state == STATE_PROBABLY_KNOWN
        assert derived.confidence == CONFIDENCE_LOW
        assert may_hide(state=derived.state, confidence=derived.confidence) is False
        decision = decide_suppression(
            knowledge_state=derived.state,
            knowledge_confidence=derived.confidence,
            importance_level="high",
        )
        assert decision.action != "hide"
        rows = list_knowledge_evidence(connection, user_id="learner", claim_id=claim_ids[0])
        assert rows[0].provenance == PROVENANCE_BOOTSTRAP_INFERRED
        assert rows[0].kind == KIND_BOOTSTRAP_INFERRED


def test_github_connection_does_not_import_knowledge(database: Database) -> None:
    _ingest_history(database, user_id="learner")
    with database.connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO github_inferred_signals (
                user_id, repository, signal_type, topic_name,
                weight, inference_version, observed_at
            ) VALUES ('learner', 'acme/api', 'language', 'Python', 0.4, 'v1', '2026-01-01T00:00:00Z')
            """
        )
        summary = inspect_bootstrap(connection, user_id="learner")
        knowledge_rows = list_knowledge_evidence(connection, user_id="learner")
    assert summary.evidence == ()
    assert knowledge_rows == []


def test_tenant_isolation_and_http_surface(client: TestClient, database: Database) -> None:
    first = client.post("/v1/sessions").json()
    second = client.post("/v1/sessions").json()
    headers_a = {"Authorization": f"Bearer {first['accessToken']}"}
    headers_b = {"Authorization": f"Bearer {second['accessToken']}"}
    user_a = first["userId"]
    event_id = _ingest_history(database, user_id=user_a)
    claim_ids = _claim_ids(database, event_id, as_of="2025-06-01T00:00:00Z")

    empty = client.get("/v1/me/knowledge/bootstrap", headers=headers_a)
    assert empty.status_code == 200
    assert empty.json()["version"] == POLICY_VERSION
    assert empty.json()["explicitClaimIds"] == []
    assert empty.json()["evidence"] == []

    created = client.post(
        "/v1/me/knowledge/bootstrap/claims",
        headers=headers_a,
        json={"claimIds": [claim_ids[0]]},
    )
    assert created.status_code == 201
    assert created.json()["claimIds"] == [claim_ids[0]]

    inspected = client.get("/v1/me/knowledge/bootstrap", headers=headers_a)
    assert inspected.json()["explicitClaimIds"] == [claim_ids[0]]
    assert inspected.json()["evidence"]

    other = client.get("/v1/me/knowledge/bootstrap", headers=headers_b)
    assert other.json()["explicitClaimIds"] == []
    assert other.json()["evidence"] == []

    checkpoint = client.put(
        "/v1/me/knowledge/bootstrap/checkpoint",
        headers=headers_a,
        json={
            "subjectKind": "event",
            "subjectId": event_id,
            "asOf": "2026-01-01T00:00:00Z",
        },
    )
    assert checkpoint.status_code == 200
    assert checkpoint.json()["claimIds"]

    missing = client.post(
        "/v1/me/knowledge/bootstrap/claims",
        headers=headers_a,
        json={"claimIds": ["claim_does_not_exist"]},
    )
    assert missing.status_code == 422

    reset = client.delete("/v1/me/knowledge/bootstrap", headers=headers_a)
    assert reset.status_code == 204
    after = client.get("/v1/me/knowledge/bootstrap", headers=headers_a)
    assert after.json()["explicitClaimIds"] == []
    assert after.json()["checkpoints"] == []


def test_bootstrap_does_not_write_delivery_watermarks(database: Database) -> None:
    event_id = _ingest_history(database, user_id="learner")
    claim_ids = _claim_ids(database, event_id, as_of="2025-06-01T00:00:00Z")
    with database.connect() as connection:
        record_explicit_bootstrap(connection, user_id="learner", claim_ids=claim_ids[:1])
        exposures = connection.execute(
            "SELECT COUNT(*) FROM user_claim_exposures WHERE user_id = 'learner'"
        ).fetchone()[0]
    assert exposures == 0


def test_knownness_gold_can_score_bootstrap_precision_and_false_suppression() -> None:
    explicit = KnowledgeEvidence(
        id="e1",
        user_id="u",
        claim_id="c1",
        event_id="ev",
        delta_id="d1",
        kind=KIND_BOOTSTRAP_EXPLICIT,
        provenance=PROVENANCE_BOOTSTRAP,
        confidence=CONFIDENCE_HIGH,
        source_id="bootstrap:explicit:s:c1",
        created_at=1,
    )
    inferred = KnowledgeEvidence(
        id="e2",
        user_id="u",
        claim_id="c2",
        event_id="ev",
        delta_id="d2",
        kind=KIND_BOOTSTRAP_INFERRED,
        provenance=PROVENANCE_BOOTSTRAP_INFERRED,
        confidence=CONFIDENCE_LOW,
        source_id="bootstrap:inferred:c2",
        created_at=2,
    )
    displayed = KnowledgeEvidence(
        id="e3",
        user_id="u",
        claim_id="c3",
        event_id="ev",
        delta_id="d3",
        kind=KIND_DISPLAYED,
        provenance="display",
        confidence="medium",
        source_id="dlv_1",
        created_at=3,
    )
    report = evaluate_bootstrap_impact(
        (
            BootstrapEvalCase(case_id="explicit", evidence=(explicit,), gold_known=True),
            BootstrapEvalCase(case_id="inferred", evidence=(inferred,), gold_known=False),
            BootstrapEvalCase(case_id="display", evidence=(displayed,), gold_known=False),
        )
    )
    assert report.case_count == 3
    assert report.precision == 1.0
    assert report.unknown_but_hidden == 0
    assert report.inferred_hide_count == 0


def test_feed_ranking_sees_bootstrap_knownness(database: Database) -> None:
    event_id = _ingest_history(database, user_id="learner")
    claim_ids = _claim_ids(database, event_id, as_of="2025-06-01T00:00:00Z")
    with database.connect() as connection:
        record_explicit_bootstrap(connection, user_id="learner", claim_ids=claim_ids[:1])
    items, _ = FeedStore(database).list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    assert items
    with database.connect() as connection:
        mapped = {
            item.delta.id: ranking_knownness(
                connection,
                user_id="learner",
                claim_id=connection.execute(
                    "SELECT claim_id FROM delta_claim_map WHERE delta_id = ?",
                    (item.delta.id,),
                ).fetchone()["claim_id"],
            )
            for item in items
        }
    assert STATE_KNOWN in mapped.values()
