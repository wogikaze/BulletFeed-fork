from __future__ import annotations

import time

from app.services.feed_projection import FeedProjector
from app.services.knowledge_evidence import (
    KIND_ALREADY_KNEW,
    KIND_DISPLAYED,
    replay_knowledge_state,
)
from app.services.knownness_decay import DECAY_POLICY_VERSION, IMPLICIT_TTL_SECONDS
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.event_store import EventStore
from app.stores.feed_store import FeedStore


def _summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_decay_feed",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_decay_feed",
                "incident_updates": [
                    {
                        "id": "upd_decay_1",
                        "status": "identified",
                        "body": "Database saturation identified.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def _project_for_user(database, user_id: str) -> tuple[str, FeedStore, list]:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", (user_id,))
    FeedProjector(database).project_event_for_user(user_id=user_id, event_id=event_id)
    store = FeedStore(database)
    items, _ = store.list_feed(user_id, relation=None, item_status=None, cursor=None, limit=50)
    assert items
    return event_id, store, items


def test_decay_policy_version_is_pinned() -> None:
    assert DECAY_POLICY_VERSION == "knownness-decay-v1"
    assert IMPLICIT_TTL_SECONDS["displayed"] == 90 * 24 * 60 * 60


def test_stale_displayed_does_not_hide_next_feed(database) -> None:
    event_id, store, items = _project_for_user(database, "user_decay")
    accepted = store.record_exposures(
        "user_decay",
        [
            {
                "delivery_id": item.delivery_id,
                "displayed_at": "2026-08-22T00:12:00Z",
                "dwell_ms": 1500,
                "visible_ratio": 0.9,
            }
            for item in items
        ],
    )
    assert accepted == len(items)
    stale_at = int(time.time()) - (200 * 24 * 60 * 60)
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE user_knowledge_evidence
            SET created_at = ?
            WHERE user_id = ? AND kind = ?
            """,
            (stale_at, "user_decay", KIND_DISPLAYED),
        )
        claim_id = connection.execute(
            """
            SELECT claim_id FROM user_knowledge_evidence
            WHERE user_id = ? AND kind = ? LIMIT 1
            """,
            ("user_decay", KIND_DISPLAYED),
        ).fetchone()["claim_id"]
        derived = replay_knowledge_state(
            connection,
            user_id="user_decay",
            claim_id=claim_id,
            now=int(time.time()),
        )
    assert derived.state == "unknown"
    after, _ = store.list_feed("user_decay", relation=None, item_status=None, cursor=None, limit=50)
    assert {item.id for item in after} == {item.id for item in items}
    detail = EventStore(database).get_event("user_decay", event_id, None)
    assert detail.unknown_facts


def test_already_knew_does_not_decay_on_event_detail(database) -> None:
    event_id, store, items = _project_for_user(database, "user_explicit")
    first = items[0]
    store.save_feedback("user_explicit", first.id, "already_knew")
    stale_at = int(time.time()) - (400 * 24 * 60 * 60)
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE user_knowledge_evidence
            SET created_at = ?
            WHERE user_id = ? AND kind = ?
            """,
            (stale_at, "user_explicit", KIND_ALREADY_KNEW),
        )
        claim_id = connection.execute(
            """
            SELECT claim_id FROM user_knowledge_evidence
            WHERE user_id = ? AND kind = ? LIMIT 1
            """,
            ("user_explicit", KIND_ALREADY_KNEW),
        ).fetchone()["claim_id"]
        derived = replay_knowledge_state(
            connection,
            user_id="user_explicit",
            claim_id=claim_id,
            now=int(time.time()),
        )
    assert derived.state == "known"
    assert derived.confidence == "high"
    detail = EventStore(database).get_event("user_explicit", event_id, None)
    known_ids = {fact.id.split(":")[0] for fact in detail.unknown_facts}
    assert claim_id not in known_ids
