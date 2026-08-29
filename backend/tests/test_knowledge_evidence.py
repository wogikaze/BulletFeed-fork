from app.db.knowledge_evidence_schema import KNOWLEDGE_EVIDENCE_TABLE
from app.services.feedback_signals import (
    assert_feedback_does_not_mutate_ledger,
    ledger_world_state,
)
from app.services.feed_projection import FeedProjector
from app.services.knowledge_evidence import (
    ACCOUNT_DELETION_TABLE,
    KIND_ALREADY_KNEW,
    KIND_BASELINE,
    KIND_DELIVERED,
    KIND_DISPLAYED,
    KIND_LEARNED_NOW,
    KIND_READ,
    PROVENANCE_BASELINE,
    PROVENANCE_DELIVERY,
    PROVENANCE_DISPLAY,
    PROVENANCE_EXPLICIT_FEEDBACK,
    PROVENANCE_READ,
    STATE_KNOWN,
    STATE_PROBABLY_KNOWN,
    STATE_UNKNOWN,
    KnowledgeEvidence,
    append_knowledge_evidence,
    derive_knowledge_state,
    list_knowledge_evidence,
    may_hide,
    presentation_for_item,
    replay_knowledge_state,
)
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore
from app.stores.me_store import MeStore


def _summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_knowledge_evidence",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_knowledge_evidence",
                "incident_updates": [
                    {
                        "id": "upd_ke_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def _project_claim(database, *, user_id: str = "learner") -> tuple[str, str, str, str]:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:01:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)",
            (user_id,),
        )
    FeedProjector(database).project_event_for_user(user_id=user_id, event_id=event_id)
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT f.id AS feed_item_id, f.event_id, f.delta_id, m.claim_id
            FROM feed_items f
            JOIN delta_claim_map m ON m.delta_id = f.delta_id
            WHERE f.user_id = ?
            ORDER BY f.updated_at DESC, f.id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        assert row is not None
        assert row["claim_id"]
        return row["feed_item_id"], row["event_id"], row["delta_id"], row["claim_id"]


def _append(
    connection,
    *,
    user_id: str,
    kind: str,
    source_id: str,
    claim_id: str,
    event_id: str,
    delta_id: str,
    created_at: int,
    evidence_id: str | None = None,
) -> bool:
    return append_knowledge_evidence(
        connection,
        user_id=user_id,
        kind=kind,
        source_id=source_id,
        claim_id=claim_id,
        event_id=event_id,
        delta_id=delta_id,
        created_at=created_at,
        evidence_id=evidence_id,
    )


def test_append_is_audit_friendly_and_linked_to_user_plus_target(database) -> None:
    item_id, event_id, delta_id, claim_id = _project_claim(database)
    del item_id
    with database.connect() as connection:
        inserted = _append(
            connection,
            user_id="learner",
            kind=KIND_DISPLAYED,
            source_id="dlv_display_1",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=10,
        )
        assert inserted is True
        rows = list_knowledge_evidence(
            connection, user_id="learner", claim_id=claim_id
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.user_id == "learner"
        assert row.claim_id == claim_id
        assert row.event_id == event_id
        assert row.delta_id == delta_id
        assert row.kind == KIND_DISPLAYED
        assert row.provenance == PROVENANCE_DISPLAY
        assert row.confidence == "medium"
        assert row.source_id == "dlv_display_1"


def test_provenance_distinguishes_delivery_display_read_feedback_baseline(database) -> None:
    _item_id, event_id, delta_id, claim_id = _project_claim(database)
    with database.connect() as connection:
        for kind, source_id, created_at in (
            (KIND_DELIVERED, "dlv_1", 1),
            (KIND_DISPLAYED, "dlv_1", 2),
            (KIND_READ, "dlv_1", 3),
            (KIND_ALREADY_KNEW, "fb_knew", 4),
            (KIND_LEARNED_NOW, "fb_learned", 5),
            (KIND_BASELINE, "chk_follow", 6),
        ):
            _append(
                connection,
                user_id="learner",
                kind=kind,
                source_id=source_id,
                claim_id=claim_id,
                event_id=event_id,
                delta_id=delta_id,
                created_at=created_at,
            )
        rows = list_knowledge_evidence(connection, user_id="learner", claim_id=claim_id)
        assert [row.kind for row in rows] == [
            KIND_DELIVERED,
            KIND_DISPLAYED,
            KIND_READ,
            KIND_ALREADY_KNEW,
            KIND_LEARNED_NOW,
            KIND_BASELINE,
        ]
        assert [row.provenance for row in rows] == [
            PROVENANCE_DELIVERY,
            PROVENANCE_DISPLAY,
            PROVENANCE_READ,
            PROVENANCE_EXPLICIT_FEEDBACK,
            PROVENANCE_EXPLICIT_FEEDBACK,
            PROVENANCE_BASELINE,
        ]


def test_repeated_delivered_exposure_stays_unknown(database) -> None:
    _item_id, event_id, delta_id, claim_id = _project_claim(database)
    with database.connect() as connection:
        for index in range(5):
            _append(
                connection,
                user_id="learner",
                kind=KIND_DELIVERED,
                source_id=f"dlv_repeat_{index}",
                claim_id=claim_id,
                event_id=event_id,
                delta_id=delta_id,
                created_at=index,
            )
        derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
        assert derived.state == STATE_UNKNOWN
        assert derived.confidence == "low"
        assert derived.visibility == "show"
        assert derived.evidence_count == 5
        assert may_hide(state=derived.state, confidence=derived.confidence) is False
        assert (
            presentation_for_item(
                state=derived.state,
                confidence=derived.confidence,
                importance_level="critical",
            )
            == "show"
        )


def test_conflicting_evidence_explicit_override_wins(database) -> None:
    _item_id, event_id, delta_id, claim_id = _project_claim(database)
    with database.connect() as connection:
        _append(
            connection,
            user_id="learner",
            kind=KIND_DELIVERED,
            source_id="dlv_conflict",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=1,
        )
        _append(
            connection,
            user_id="learner",
            kind=KIND_DISPLAYED,
            source_id="dlv_conflict",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=2,
        )
        after_display = replay_knowledge_state(
            connection, user_id="learner", claim_id=claim_id
        )
        assert after_display.state == STATE_PROBABLY_KNOWN
        assert after_display.visibility == "demote"

        _append(
            connection,
            user_id="learner",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_conflict_knew",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=3,
        )
        after_knew = replay_knowledge_state(
            connection, user_id="learner", claim_id=claim_id
        )
        assert after_knew.state == STATE_KNOWN
        assert after_knew.confidence == "high"
        assert after_knew.visibility == "hide"

        _append(
            connection,
            user_id="learner",
            kind=KIND_LEARNED_NOW,
            source_id="fb_conflict_learned",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=4,
        )
        _append(
            connection,
            user_id="learner",
            kind=KIND_READ,
            source_id="dlv_later_read",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=5,
        )
        after_later_implicit = replay_knowledge_state(
            connection, user_id="learner", claim_id=claim_id
        )
        assert after_later_implicit.state == STATE_KNOWN
        assert after_later_implicit.visibility == "hide"


def test_state_is_replayable_from_out_of_order_history(database) -> None:
    _item_id, event_id, delta_id, claim_id = _project_claim(database)
    with database.connect() as connection:
        _append(
            connection,
            user_id="learner",
            kind=KIND_READ,
            source_id="dlv_replay_read",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=30,
            evidence_id="knev_z",
        )
        _append(
            connection,
            user_id="learner",
            kind=KIND_DELIVERED,
            source_id="dlv_replay_delivered",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=10,
            evidence_id="knev_a",
        )
        _append(
            connection,
            user_id="learner",
            kind=KIND_BASELINE,
            source_id="chk_replay",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=20,
            evidence_id="knev_m",
        )
        rows = list_knowledge_evidence(connection, user_id="learner", claim_id=claim_id)
        assert [row.kind for row in rows] == [KIND_DELIVERED, KIND_BASELINE, KIND_READ]
        stored = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
        shuffled = [
            KnowledgeEvidence(
                id="knev_z",
                user_id="learner",
                claim_id=claim_id,
                event_id=event_id,
                delta_id=delta_id,
                kind=KIND_READ,
                provenance=PROVENANCE_READ,
                confidence="medium",
                source_id="dlv_replay_read",
                created_at=30,
            ),
            KnowledgeEvidence(
                id="knev_a",
                user_id="learner",
                claim_id=claim_id,
                event_id=event_id,
                delta_id=delta_id,
                kind=KIND_DELIVERED,
                provenance=PROVENANCE_DELIVERY,
                confidence="low",
                source_id="dlv_replay_delivered",
                created_at=10,
            ),
            KnowledgeEvidence(
                id="knev_m",
                user_id="learner",
                claim_id=claim_id,
                event_id=event_id,
                delta_id=delta_id,
                kind=KIND_BASELINE,
                provenance=PROVENANCE_BASELINE,
                confidence="high",
                source_id="chk_replay",
                created_at=20,
            ),
        ]
        assert derive_knowledge_state(shuffled) == stored
        assert stored.state == STATE_KNOWN
        assert stored.visibility == "hide"


def test_same_delivery_id_and_feedback_id_are_idempotent(database) -> None:
    _item_id, event_id, delta_id, claim_id = _project_claim(database)
    with database.connect() as connection:
        first = _append(
            connection,
            user_id="learner",
            kind=KIND_DELIVERED,
            source_id="dlv_shared",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=1,
        )
        second = _append(
            connection,
            user_id="learner",
            kind=KIND_DELIVERED,
            source_id="dlv_shared",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=99,
        )
        displayed = _append(
            connection,
            user_id="learner",
            kind=KIND_DISPLAYED,
            source_id="dlv_shared",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=2,
        )
        displayed_again = _append(
            connection,
            user_id="learner",
            kind=KIND_DISPLAYED,
            source_id="dlv_shared",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=100,
        )
        feedback = _append(
            connection,
            user_id="learner",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_shared",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=3,
        )
        feedback_again = _append(
            connection,
            user_id="learner",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_shared",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=101,
        )
        assert first is True
        assert second is False
        assert displayed is True
        assert displayed_again is False
        assert feedback is True
        assert feedback_again is False
        rows = list_knowledge_evidence(connection, user_id="learner", claim_id=claim_id)
        assert len(rows) == 3
        delivered = next(row for row in rows if row.kind == KIND_DELIVERED)
        assert delivered.created_at == 1


def test_uncertain_evidence_never_hides_high_value_unknown() -> None:
    delivered_only = derive_knowledge_state(
        [
            KnowledgeEvidence(
                id="e1",
                user_id="learner",
                claim_id="claim_x",
                event_id="event_x",
                delta_id="delta_x",
                kind=KIND_DELIVERED,
                provenance=PROVENANCE_DELIVERY,
                confidence="low",
                source_id="dlv_x",
                created_at=1,
            )
        ]
    )
    displayed = derive_knowledge_state(
        [
            KnowledgeEvidence(
                id="e2",
                user_id="learner",
                claim_id="claim_x",
                event_id="event_x",
                delta_id="delta_x",
                kind=KIND_DISPLAYED,
                provenance=PROVENANCE_DISPLAY,
                confidence="medium",
                source_id="dlv_x",
                created_at=2,
            )
        ]
    )
    assert delivered_only.state == STATE_UNKNOWN
    assert delivered_only.visibility == "show"
    assert displayed.state == STATE_PROBABLY_KNOWN
    assert displayed.visibility == "demote"
    for derived in (delivered_only, displayed):
        assert may_hide(state=derived.state, confidence=derived.confidence) is False
        assert (
            presentation_for_item(
                state=derived.state,
                confidence=derived.confidence,
                importance_level="critical",
            )
            != "hide"
        )
        assert (
            presentation_for_item(
                state=derived.state,
                confidence=derived.confidence,
                importance_level="high",
            )
            != "hide"
        )


def test_ledger_isolation_when_appending_evidence(database) -> None:
    _item_id, event_id, delta_id, claim_id = _project_claim(database)
    with database.connect() as connection:
        before = ledger_world_state(connection)
        claim_values = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT id, value_text, detail_text FROM state_claims ORDER BY id"
            )
        )
        for kind, source_id, created_at in (
            (KIND_DELIVERED, "dlv_ledger", 1),
            (KIND_DISPLAYED, "dlv_ledger", 2),
            (KIND_READ, "dlv_ledger", 3),
            (KIND_ALREADY_KNEW, "fb_ledger", 4),
            (KIND_BASELINE, "chk_ledger", 5),
        ):
            _append(
                connection,
                user_id="learner",
                kind=kind,
                source_id=source_id,
                claim_id=claim_id,
                event_id=event_id,
                delta_id=delta_id,
                created_at=created_at,
            )
        after = ledger_world_state(connection)
        assert_feedback_does_not_mutate_ledger(before, after)
        assert tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT id, value_text, detail_text FROM state_claims ORDER BY id"
            )
        ) == claim_values
        assert list_knowledge_evidence(connection, user_id="learner", claim_id=claim_id)


def test_user_deletion_removes_personal_evidence_not_ledger(database) -> None:
    assert ACCOUNT_DELETION_TABLE == KNOWLEDGE_EVIDENCE_TABLE
    _item_id, event_id, delta_id, claim_id = _project_claim(database, user_id="keeper")
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('gone', 0)")
        _append(
            connection,
            user_id="gone",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_gone",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=1,
        )
        _append(
            connection,
            user_id="keeper",
            kind=KIND_DISPLAYED,
            source_id="dlv_keeper",
            claim_id=claim_id,
            event_id=event_id,
            delta_id=delta_id,
            created_at=1,
        )
        before = ledger_world_state(connection)

    MeStore(database).delete_account("gone")

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(before, ledger_world_state(connection))
        leftover_gone = connection.execute(
            "SELECT COUNT(*) FROM user_knowledge_evidence WHERE user_id = 'gone'"
        ).fetchone()[0]
        leftover_keeper = connection.execute(
            "SELECT COUNT(*) FROM user_knowledge_evidence WHERE user_id = 'keeper'"
        ).fetchone()[0]
        assert leftover_gone == 0
        assert leftover_keeper == 1
        assert connection.execute(
            "SELECT 1 FROM state_claims WHERE id = ?",
            (claim_id,),
        ).fetchone()


def test_get_feed_records_delivered_but_does_not_mark_known(database) -> None:
    item_id, event_id, delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    assert delivered
    assert delivered[0].id == item_id

    with database.connect() as connection:
        watermark = connection.execute(
            """
            SELECT state FROM user_claim_exposures
            WHERE user_id = 'learner' AND claim_id = ?
            """,
            (claim_id,),
        ).fetchone()
        assert watermark["state"] == "delivered"
        rows = list_knowledge_evidence(connection, user_id="learner", claim_id=claim_id)
        assert rows
        assert {row.kind for row in rows} == {KIND_DELIVERED}
        derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
        assert derived.state == STATE_UNKNOWN
        assert derived.visibility == "show"
        assert may_hide(state=derived.state, confidence=derived.confidence) is False
        assert rows[0].event_id == event_id
        assert rows[0].delta_id == delta_id


def test_display_read_and_feedback_extend_watermarks_without_replacing_them(
    database,
) -> None:
    item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    store.record_exposures(
        "learner",
        [{"delivery_id": delivered[0].delivery_id, "displayed_at": "2026-08-22T00:02:00Z"}],
    )
    store.mark_read("learner", item_id)
    store.save_feedback("learner", item_id, "already_knew")

    with database.connect() as connection:
        watermark = connection.execute(
            """
            SELECT state, displayed_at, read_at FROM user_claim_exposures
            WHERE user_id = 'learner' AND claim_id = ?
            """,
            (claim_id,),
        ).fetchone()
        assert watermark["state"] == "read"
        assert watermark["displayed_at"] == "2026-08-22T00:02:00Z"
        assert watermark["read_at"]
        kinds = {
            row.kind
            for row in list_knowledge_evidence(
                connection, user_id="learner", claim_id=claim_id
            )
        }
        assert {KIND_DELIVERED, KIND_DISPLAYED, KIND_READ, KIND_ALREADY_KNEW} <= kinds
        derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
        assert derived.state == STATE_KNOWN
        replay = store.record_exposures(
            "learner",
            [
                {
                    "delivery_id": delivered[0].delivery_id,
                    "displayed_at": "2026-08-22T00:09:00Z",
                }
            ],
        )
        assert replay == 0
        displayed_rows = [
            row
            for row in list_knowledge_evidence(
                connection, user_id="learner", claim_id=claim_id
            )
            if row.kind == KIND_DISPLAYED
        ]
        assert len(displayed_rows) == 1
