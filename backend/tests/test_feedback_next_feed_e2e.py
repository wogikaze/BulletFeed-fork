"""#317: explicit feedback must change the next GET /feed on the same candidates.

Learning lives in ranking overlay only. Event/Claim/Delta rows stay untouched.
One click is not enough; MIN_SAMPLE_SIZE important marks on a source type
must lift held-out siblings of that type on the following feed page.
"""

from fastapi.testclient import TestClient

from app.database import Database
from app.services.feedback_signals import (
    assert_feedback_does_not_mutate_ledger,
    ledger_world_state,
)
from app.services.ranking import evaluate_importance
from app.services.ranking_feedback import MIN_SAMPLE_SIZE, PERSONALIZATION_VERSION


def _user_id(database: Database) -> str:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        return user["id"]


def _insert_item(
    connection,
    *,
    user_id: str,
    item_id: str,
    event_id: str,
    source_type: str,
    updated_at: str,
    delta_type: str = "detail",
) -> None:
    connection.execute(
        """
        INSERT INTO events (
            id, title, summary, current_phase, current_summary,
            current_since, current_confidence, updated_at
        ) VALUES (?, ?, '', 'published', '', ?, 'high', ?)
        """,
        (event_id, f"{source_type} {event_id}", updated_at, updated_at),
    )
    connection.execute(
        """
        INSERT INTO ledger_events (
            id, source_type, source_key, source_event_id, title, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_id, source_type, event_id, event_id, event_id, updated_at),
    )
    delta_id = f"d_{item_id}"
    connection.execute(
        """
        INSERT INTO deltas (
            id, event_id, type, summary, before_text, after_text, occurred_at
        ) VALUES (?, ?, ?, '', '', '', ?)
        """,
        (delta_id, event_id, delta_type, updated_at),
    )
    importance = evaluate_importance(source_type=source_type, delta_type=delta_type)
    connection.execute(
        """
        INSERT INTO feed_items (
            id, user_id, event_id, delta_id, title,
            importance_level, importance_reason, importance_confidence,
            relation_level, relation_reason, matched_topics_json,
            matched_repos_json, personalization_rank,
            status, dismissed, marked_important, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reference', '', '[]', '[]', 0, 'unread', 0, 0, ?)
        """,
        (
            item_id,
            user_id,
            event_id,
            delta_id,
            event_id,
            importance.level,
            importance.reason,
            importance.confidence,
            updated_at,
        ),
    )


def _seed_same_candidate_set(database: Database, user_id: str) -> None:
    with database.connect() as connection:
        for index in range(MIN_SAMPLE_SIZE):
            _insert_item(
                connection,
                user_id=user_id,
                item_id=f"nfeed_train_{index}",
                event_id=f"ev_nfeed_train_{index}",
                source_type="github_release",
                updated_at=f"2026-08-20T00:0{index}:00Z",
            )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_held_release",
            event_id="ev_nfeed_held_release",
            source_type="github_release",
            updated_at="2026-08-21T00:00:00Z",
        )
        _insert_item(
            connection,
            user_id=user_id,
            item_id="nfeed_held_rss",
            event_id="ev_nfeed_held_rss",
            source_type="rss_atom",
            updated_at="2026-08-22T00:00:00Z",
            delta_type="new_fact",
        )


def _feed_ids(client: TestClient, auth_headers: dict[str, str]) -> list[str]:
    response = client.get("/v1/feed", headers=auth_headers, params={"limit": 50})
    assert response.status_code == 200
    return [item["id"] for item in response.json()["items"]]


def test_one_important_mark_does_not_reorder_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_same_candidate_set(database, user_id)
    before = _feed_ids(client, auth_headers)
    assert before.index("nfeed_held_rss") < before.index("nfeed_held_release")

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    marked = client.post(
        "/v1/feed/items/nfeed_train_0/feedback",
        headers=auth_headers,
        json={"type": "important"},
    )
    assert marked.status_code == 200
    after = _feed_ids(client, auth_headers)
    assert after.index("nfeed_held_rss") < after.index("nfeed_held_release")
    assert "nfeed_held_release" in after
    assert "nfeed_held_rss" in after

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_release",),
        ).fetchone()
        assert PERSONALIZATION_VERSION not in held["importance_reason"]


def test_enough_important_feedback_lifts_held_out_siblings_on_next_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    user_id = _user_id(database)
    _seed_same_candidate_set(database, user_id)
    before = _feed_ids(client, auth_headers)
    assert before.index("nfeed_held_rss") < before.index("nfeed_held_release")

    with database.connect() as connection:
        ledger_before = ledger_world_state(connection)

    for index in range(MIN_SAMPLE_SIZE):
        response = client.post(
            f"/v1/feed/items/nfeed_train_{index}/feedback",
            headers=auth_headers,
            json={"type": "important"},
        )
        assert response.status_code == 200

    after = _feed_ids(client, auth_headers)
    assert after.index("nfeed_held_release") < after.index("nfeed_held_rss")
    assert set(before) == set(after)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(ledger_before, ledger_world_state(connection))
        held = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_release",),
        ).fetchone()
        rss = connection.execute(
            "SELECT importance_level, importance_reason FROM feed_items WHERE id = ?",
            ("nfeed_held_rss",),
        ).fetchone()
    assert held["importance_level"] == "high"
    assert PERSONALIZATION_VERSION in held["importance_reason"]
    assert rss["importance_level"] == "medium"
    assert PERSONALIZATION_VERSION not in rss["importance_reason"]
