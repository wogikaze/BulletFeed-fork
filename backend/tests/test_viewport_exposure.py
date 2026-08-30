from app.schemas.feed import ExposuresRequest
from app.services.feed_projection import FeedProjector
from app.services.knowledge_evidence import (
    KIND_DELIVERED,
    KIND_DISPLAYED,
    STATE_UNKNOWN,
    list_knowledge_evidence,
    may_hide,
    replay_knowledge_state,
)
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.services.viewport_exposure import (
    MIN_DWELL_MS,
    MIN_VISIBLE_RATIO,
    POLICY_VERSION,
    is_meaningful_display,
)
from app.stores.feed_store import FeedStore


def _summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_viewport_exposure",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_viewport_exposure",
                "incident_updates": [
                    {
                        "id": "upd_vp_1",
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
        return row["feed_item_id"], row["event_id"], row["delta_id"], row["claim_id"]


def _knownness(database, user_id: str, claim_id: str) -> str | None:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT state FROM user_claim_exposures
            WHERE user_id = ? AND claim_id = ?
            """,
            (user_id, claim_id),
        ).fetchone()
    return None if row is None else row["state"]


def _evidence_kinds(database, user_id: str, claim_id: str) -> set[str]:
    with database.connect() as connection:
        return {
            row.kind
            for row in list_knowledge_evidence(
                connection, user_id=user_id, claim_id=claim_id
            )
        }


def _exposure_row(database, delivery_id: str):
    with database.connect() as connection:
        return connection.execute(
            """
            SELECT dwell_ms, visible_ratio, policy_version, detail_opened
            FROM exposures
            WHERE delivery_id = ?
            """,
            (delivery_id,),
        ).fetchone()


def test_exposure_request_accepts_optional_metrics() -> None:
    body = ExposuresRequest.model_validate(
        {
            "items": [
                {
                    "deliveryId": "dlv_1",
                    "displayedAt": "2026-08-22T00:00:00Z",
                    "dwellMs": 1000,
                    "visibleRatio": 0.5,
                    "detailOpened": False,
                }
            ]
        }
    )
    assert body.items[0].dwell_ms == 1000
    assert body.items[0].visible_ratio == 0.5
    compat = ExposuresRequest.model_validate(
        {
            "items": [
                {"deliveryId": "dlv_2", "displayedAt": "2026-08-22T00:00:00Z"}
            ]
        }
    )
    assert compat.items[0].dwell_ms is None
    assert compat.items[0].visible_ratio is None


def test_policy_version_and_thresholds_are_documented() -> None:
    assert POLICY_VERSION == "viewport-exposure-v2"
    assert MIN_DWELL_MS == 1000
    assert MIN_VISIBLE_RATIO == 0.50


def test_missing_or_partial_metrics_are_not_displayed() -> None:
    assert is_meaningful_display() is False
    assert is_meaningful_display(dwell_ms=None, visible_ratio=None) is False
    assert is_meaningful_display(dwell_ms=2_000, visible_ratio=None) is False
    assert is_meaningful_display(dwell_ms=None, visible_ratio=1.0) is False
    assert is_meaningful_display(dwell_ms=0, visible_ratio=0.0) is False
    assert is_meaningful_display(dwell_ms=None, visible_ratio=None, detail_opened=True)


def test_too_brief_or_tiny_visibility_is_not_meaningful() -> None:
    assert is_meaningful_display(dwell_ms=200, visible_ratio=1.0) is False
    assert is_meaningful_display(dwell_ms=5_000, visible_ratio=0.05) is False
    assert is_meaningful_display(dwell_ms=MIN_DWELL_MS, visible_ratio=MIN_VISIBLE_RATIO)
    assert is_meaningful_display(dwell_ms=200, visible_ratio=0.05, detail_opened=True)


def test_get_feed_does_not_mark_displayed(database) -> None:
    _item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    assert delivered
    assert _knownness(database, "learner", claim_id) == "delivered"
    assert _evidence_kinds(database, "learner", claim_id) == {KIND_DELIVERED}
    with database.connect() as connection:
        derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
    assert derived.state == STATE_UNKNOWN
    assert derived.visibility == "show"
    assert may_hide(state=derived.state, confidence=derived.confidence) is False
    assert _exposure_row(database, delivered[0].delivery_id) is None


def test_exposure_without_metrics_stays_delivered(database) -> None:
    _item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    accepted = store.record_exposures(
        "learner",
        [{"delivery_id": delivered[0].delivery_id, "displayed_at": "2026-08-22T00:02:00Z"}],
    )
    assert accepted == 0
    assert _knownness(database, "learner", claim_id) == "delivered"
    assert KIND_DISPLAYED not in _evidence_kinds(database, "learner", claim_id)
    assert _exposure_row(database, delivered[0].delivery_id) is None


def test_too_brief_visibility_does_not_count_as_displayed(database) -> None:
    _item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    accepted = store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivered[0].delivery_id,
                "displayed_at": "2026-08-22T00:02:00Z",
                "dwell_ms": 200,
                "visible_ratio": 1.0,
            }
        ],
    )
    assert accepted == 0
    assert _knownness(database, "learner", claim_id) == "delivered"
    assert _evidence_kinds(database, "learner", claim_id) == {KIND_DELIVERED}
    assert _exposure_row(database, delivered[0].delivery_id) is None
    with database.connect() as connection:
        derived = replay_knowledge_state(connection, user_id="learner", claim_id=claim_id)
    assert derived.state == STATE_UNKNOWN
    assert derived.visibility == "show"


def test_tiny_visibility_does_not_count_as_displayed(database) -> None:
    _item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    accepted = store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivered[0].delivery_id,
                "displayed_at": "2026-08-22T00:02:00Z",
                "dwell_ms": 5_000,
                "visible_ratio": 0.05,
            }
        ],
    )
    assert accepted == 0
    assert _knownness(database, "learner", claim_id) == "delivered"
    assert KIND_DISPLAYED not in _evidence_kinds(database, "learner", claim_id)
    assert _exposure_row(database, delivered[0].delivery_id) is None


def test_meaningful_metrics_record_displayed_and_audit_fields(database) -> None:
    _item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    accepted = store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivered[0].delivery_id,
                "displayed_at": "2026-08-22T00:02:00Z",
                "dwell_ms": MIN_DWELL_MS,
                "visible_ratio": MIN_VISIBLE_RATIO,
            }
        ],
    )
    assert accepted == 1
    assert _knownness(database, "learner", claim_id) == "displayed"
    assert KIND_DISPLAYED in _evidence_kinds(database, "learner", claim_id)
    row = _exposure_row(database, delivered[0].delivery_id)
    assert row["dwell_ms"] == MIN_DWELL_MS
    assert row["visible_ratio"] == MIN_VISIBLE_RATIO
    assert row["policy_version"] == POLICY_VERSION
    assert row["detail_opened"] == 0
    replay = store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivered[0].delivery_id,
                "displayed_at": "2026-08-22T00:09:00Z",
                "dwell_ms": 4_000,
                "visible_ratio": 1.0,
            }
        ],
    )
    assert replay == 0


def test_detail_open_counts_even_when_dwell_is_brief(database) -> None:
    _item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    accepted = store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivered[0].delivery_id,
                "displayed_at": "2026-08-22T00:02:00Z",
                "dwell_ms": 50,
                "visible_ratio": 0.1,
                "detail_opened": True,
            }
        ],
    )
    assert accepted == 1
    assert _knownness(database, "learner", claim_id) == "displayed"
    row = _exposure_row(database, delivered[0].delivery_id)
    assert row["detail_opened"] == 1


def test_partial_metrics_stay_delivered_but_detail_open_still_counts(database) -> None:
    _item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    delivery_id = delivered[0].delivery_id
    rejected = store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivery_id,
                "displayed_at": "2026-08-22T00:02:00Z",
                "dwell_ms": 4_000,
            }
        ],
    )
    assert rejected == 0
    assert _knownness(database, "learner", claim_id) == "delivered"
    accepted = store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivery_id,
                "displayed_at": "2026-08-22T00:03:00Z",
                "detail_opened": True,
            }
        ],
    )
    assert accepted == 1
    assert _knownness(database, "learner", claim_id) == "displayed"


def test_later_meaningful_post_can_follow_rejected_transient(database) -> None:
    _item_id, _event_id, _delta_id, claim_id = _project_claim(database)
    store = FeedStore(database)
    delivered, _ = store.list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    delivery_id = delivered[0].delivery_id
    store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivery_id,
                "displayed_at": "2026-08-22T00:02:00Z",
                "dwell_ms": 80,
                "visible_ratio": 0.2,
            }
        ],
    )
    assert _knownness(database, "learner", claim_id) == "delivered"
    accepted = store.record_exposures(
        "learner",
        [
            {
                "delivery_id": delivery_id,
                "displayed_at": "2026-08-22T00:03:00Z",
                "dwell_ms": 1_200,
                "visible_ratio": 0.8,
            }
        ],
    )
    assert accepted == 1
    assert _knownness(database, "learner", claim_id) == "displayed"
    assert KIND_DISPLAYED in _evidence_kinds(database, "learner", claim_id)
