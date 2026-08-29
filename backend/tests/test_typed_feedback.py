from fastapi.testclient import TestClient

from app.database import Database
from app.db.seed import seed_catalog, seed_user_workspace
from app.services.feed_projection import FeedProjector
from app.services.feedback_signals import (
    FAMILY_KNOWLEDGE,
    FAMILY_RANKING,
    assert_feedback_does_not_mutate_ledger,
    latest_family_for_item,
    latest_type_for_family,
    ledger_world_state,
)
from app.services.ranking_feedback import apply_feedback_ranking
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def _seed_demo_workspace(database: Database) -> None:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        seed_catalog(connection)
        seed_user_workspace(connection, user["id"])


def _current_user_id(database: Database) -> str:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        return user["id"]


def _statuspage_summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_typed_fb",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_typed_fb",
                "incident_updates": [
                    {
                        "id": "upd_typed_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_typed_2",
                        "status": "identified",
                        "body": "Database saturation identified.",
                        "created_at": "2026-08-22T00:10:00Z",
                        "updated_at": "2026-08-22T00:10:00Z",
                        "display_at": "2026-08-22T00:10:00Z",
                    },
                ],
            }
        ]
    }


def _project_statuspage_item(database: Database, *, user_id: str = "learner") -> tuple[str, str]:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_statuspage_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    with database.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)", (user_id,))
    FeedProjector(database).project_event_for_user(user_id=user_id, event_id=event_id)
    with database.connect() as connection:
        item = connection.execute(
            """
            SELECT id FROM feed_items
            WHERE user_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        assert item is not None
        return item["id"], event_id


def _feedback_rows(connection, *, user_id: str, feed_item_id: str) -> list:
    return list(
        connection.execute(
            """
            SELECT type, family, superseded, event_id, delta_id, claim_id, created_at
            FROM feedback
            WHERE user_id = ? AND feed_item_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (user_id, feed_item_id),
        ).fetchall()
    )


def _exposure_snapshot(connection, *, user_id: str) -> tuple:
    return tuple(
        tuple(row)
        for row in connection.execute(
            """
            SELECT user_id, claim_id, delivery_id, state, displayed_at, read_at, delivery_count
            FROM user_claim_exposures
            WHERE user_id = ?
            ORDER BY claim_id
            """,
            (user_id,),
        )
    )


def test_rejects_unknown_feedback_type(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_workspace(database)
    feed = client.get("/v1/feed", headers=auth_headers).json()["items"]
    target = feed[0]
    response = client.post(
        f"/v1/feed/items/{target['id']}/feedback",
        headers=auth_headers,
        json={"type": "hide_topic"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_accepts_expanded_feedback_types_and_keeps_ranking_compat(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_workspace(database)
    user_id = _current_user_id(database)
    with database.connect() as connection:
        topics_before = connection.execute(
            "SELECT COUNT(*) AS count FROM topics WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
    feed = client.get("/v1/feed", headers=auth_headers).json()["items"]
    important_item = next(item for item in feed if item["eventId"] == "workers-runtime")
    dismissed_item = next(item for item in feed if item["eventId"] == "kotlin-release")
    follow_item = next(item for item in feed if item["eventId"] == "openai-pricing")
    knowledge_item = next(item for item in feed if item["eventId"] == "android-security")

    important = client.post(
        f"/v1/feed/items/{important_item['id']}/feedback",
        headers=auth_headers,
        json={"type": "important"},
    )
    assert important.status_code == 200
    assert important.json()["type"] == "important"

    hide = client.post(
        f"/v1/feed/items/{dismissed_item['id']}/feedback",
        headers=auth_headers,
        json={"type": "not_relevant"},
    )
    assert hide.status_code == 200
    remaining = client.get("/v1/feed", headers=auth_headers).json()["items"]
    remaining_ids = {item["id"] for item in remaining}
    assert dismissed_item["id"] not in remaining_ids
    assert important_item["id"] in remaining_ids

    follow = client.post(
        f"/v1/feed/items/{follow_item['id']}/feedback",
        headers=auth_headers,
        json={"type": "follow"},
    )
    assert follow.status_code == 200
    assert follow.json()["type"] == "follow"

    less = client.post(
        f"/v1/feed/items/{follow_item['id']}/feedback",
        headers=auth_headers,
        json={"type": "less_like_this"},
    )
    assert less.status_code == 200
    after_less = {item["id"] for item in client.get("/v1/feed", headers=auth_headers).json()["items"]}
    assert follow_item["id"] in after_less

    knew = client.post(
        f"/v1/feed/items/{knowledge_item['id']}/feedback",
        headers=auth_headers,
        json={"type": "already_knew"},
    )
    learned = client.post(
        f"/v1/feed/items/{knowledge_item['id']}/feedback",
        headers=auth_headers,
        json={"type": "learned_now"},
    )
    assert knew.status_code == 200
    assert learned.status_code == 200
    assert learned.json()["type"] == "learned_now"

    with database.connect() as connection:
        important_row = connection.execute(
            "SELECT marked_important, dismissed FROM feed_items WHERE id = ?",
            (important_item["id"],),
        ).fetchone()
        assert important_row["marked_important"] == 1
        assert important_row["dismissed"] == 0
        follow_row = connection.execute(
            "SELECT following FROM event_follows WHERE user_id = ? AND event_id = ?",
            (user_id, "openai-pricing"),
        ).fetchone()
        assert follow_row["following"] == 1
        knowledge = connection.execute(
            """
            SELECT signal, superseded FROM user_knowledge_signals
            WHERE user_id = ? AND feed_item_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (user_id, knowledge_item["id"]),
        ).fetchall()
        assert [row["signal"] for row in knowledge] == ["already_knew", "learned_now"]
        assert knowledge[0]["superseded"] == 1
        assert knowledge[1]["superseded"] == 0
        less_row = connection.execute(
            "SELECT dismissed FROM feed_items WHERE id = ?",
            (follow_item["id"],),
        ).fetchone()
        assert less_row["dismissed"] == 0
        topics = connection.execute(
            "SELECT COUNT(*) AS count FROM topics WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
        assert topics == topics_before


def test_repeated_feedback_is_append_only_with_latest_state(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_workspace(database)
    feed = client.get("/v1/feed", headers=auth_headers).json()["items"]
    target = next(item for item in feed if item["eventId"] == "workers-runtime")
    user_id = _current_user_id(database)

    first = client.post(
        f"/v1/feed/items/{target['id']}/feedback",
        headers=auth_headers,
        json={"type": "important"},
    )
    second = client.post(
        f"/v1/feed/items/{target['id']}/feedback",
        headers=auth_headers,
        json={"type": "important"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    with database.connect() as connection:
        rows = _feedback_rows(connection, user_id=user_id, feed_item_id=target["id"])
        assert len(rows) == 2
        assert [row["type"] for row in rows] == ["important", "important"]
        assert rows[0]["superseded"] == 1
        assert rows[1]["superseded"] == 0
        assert latest_type_for_family(
            connection,
            user_id=user_id,
            feed_item_id=target["id"],
            family=FAMILY_RANKING,
        ) == "important"
        flags = connection.execute(
            "SELECT marked_important, dismissed FROM feed_items WHERE id = ?",
            (target["id"],),
        ).fetchone()
        assert flags["marked_important"] == 1
        assert flags["dismissed"] == 0


def test_undo_and_change_keep_history(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_workspace(database)
    feed = client.get("/v1/feed", headers=auth_headers).json()["items"]
    target = next(item for item in feed if item["eventId"] == "kotlin-release")
    user_id = _current_user_id(database)

    client.post(
        f"/v1/feed/items/{target['id']}/feedback",
        headers=auth_headers,
        json={"type": "not_relevant"},
    )
    hidden = {item["id"] for item in client.get("/v1/feed", headers=auth_headers).json()["items"]}
    assert target["id"] not in hidden

    change = client.post(
        f"/v1/feed/items/{target['id']}/feedback",
        headers=auth_headers,
        json={"type": "important"},
    )
    assert change.status_code == 200
    restored = {item["id"] for item in client.get("/v1/feed", headers=auth_headers).json()["items"]}
    assert target["id"] in restored

    undo = client.post(
        f"/v1/feed/items/{target['id']}/feedback",
        headers=auth_headers,
        json={"type": "undo"},
    )
    assert undo.status_code == 200
    assert undo.json()["type"] == "undo"

    with database.connect() as connection:
        rows = _feedback_rows(connection, user_id=user_id, feed_item_id=target["id"])
        assert [row["type"] for row in rows] == ["not_relevant", "important", "undo"]
        assert [row["family"] for row in rows] == [
            FAMILY_RANKING,
            FAMILY_RANKING,
            FAMILY_RANKING,
        ]
        assert [row["superseded"] for row in rows] == [1, 1, 0]
        assert latest_type_for_family(
            connection,
            user_id=user_id,
            feed_item_id=target["id"],
            family=FAMILY_RANKING,
        ) == "undo"
        flags = connection.execute(
            "SELECT marked_important, dismissed FROM feed_items WHERE id = ?",
            (target["id"],),
        ).fetchone()
        assert flags["marked_important"] == 0
        assert flags["dismissed"] == 0


def test_follow_upserts_event_follows_without_touching_claims(database: Database) -> None:
    item_id, event_id = _project_statuspage_item(database)
    store = FeedStore(database)
    with database.connect() as connection:
        before = ledger_world_state(connection)
        claim_count = connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0]
        assert claim_count > 0

    store.save_feedback("learner", item_id, "follow")
    store.save_feedback("learner", item_id, "follow")
    store.save_feedback("learner", item_id, "undo")

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(before, ledger_world_state(connection))
        follow = connection.execute(
            "SELECT following FROM event_follows WHERE user_id = ? AND event_id = ?",
            ("learner", event_id),
        ).fetchone()
        assert follow["following"] == 0
        rows = _feedback_rows(connection, user_id="learner", feed_item_id=item_id)
        assert [row["type"] for row in rows] == ["follow", "follow", "undo"]
        assert rows[0]["event_id"] == event_id
        assert rows[0]["delta_id"]
        assert rows[0]["claim_id"]
        assert connection.execute("SELECT COUNT(*) FROM state_claims").fetchone()[0] == claim_count


def test_knowledge_signals_never_mutate_ledger_or_observations(database: Database) -> None:
    item_id, event_id = _project_statuspage_item(database)
    store = FeedStore(database)
    with database.connect() as connection:
        before = ledger_world_state(connection)
        exposures_before = _exposure_snapshot(connection, user_id="learner")
        observations_before = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        claim_values = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT id, value_text, detail_text FROM state_claims ORDER BY id"
            )
        )

    store.save_feedback("learner", item_id, "already_knew")
    store.save_feedback("learner", item_id, "learned_now")

    with database.connect() as connection:
        after = ledger_world_state(connection)
        assert_feedback_does_not_mutate_ledger(before, after)
        assert after["counts"]["events"] == before["counts"]["events"]
        assert after["counts"]["deltas"] == before["counts"]["deltas"]
        assert after["counts"]["state_claims"] == before["counts"]["state_claims"]
        assert after["counts"]["claim_relations"] == before["counts"]["claim_relations"]
        assert after["hashes"] == before["hashes"]
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == observations_before
        assert _exposure_snapshot(connection, user_id="learner") == exposures_before
        assert tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT id, value_text, detail_text FROM state_claims ORDER BY id"
            )
        ) == claim_values
        flags = connection.execute(
            "SELECT marked_important, dismissed, status FROM feed_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        assert flags["marked_important"] == 0
        assert flags["dismissed"] == 0
        knowledge = connection.execute(
            """
            SELECT signal, event_id, claim_id, superseded
            FROM user_knowledge_signals
            WHERE user_id = 'learner' AND feed_item_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (item_id,),
        ).fetchall()
        assert [row["signal"] for row in knowledge] == ["already_knew", "learned_now"]
        assert knowledge[0]["superseded"] == 1
        assert knowledge[1]["event_id"] == event_id
        assert knowledge[1]["claim_id"]
        assert latest_family_for_item(
            connection, user_id="learner", feed_item_id=item_id
        ) == FAMILY_KNOWLEDGE

    store.save_feedback("learner", item_id, "undo")
    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(before, ledger_world_state(connection))
        active = connection.execute(
            """
            SELECT COUNT(*) FROM user_knowledge_signals
            WHERE user_id = 'learner' AND feed_item_id = ? AND superseded = 0
            """,
            (item_id,),
        ).fetchone()[0]
        assert active == 0


def test_all_typed_signals_leave_canonical_world_state_untouched(database: Database) -> None:
    item_id, _event_id = _project_statuspage_item(database)
    store = FeedStore(database)
    with database.connect() as connection:
        before = ledger_world_state(connection)

    for feedback_type in (
        "important",
        "not_relevant",
        "follow",
        "already_knew",
        "learned_now",
        "less_like_this",
        "undo",
    ):
        store.save_feedback("learner", item_id, feedback_type)

    with database.connect() as connection:
        assert_feedback_does_not_mutate_ledger(before, ledger_world_state(connection))
        rows = _feedback_rows(connection, user_id="learner", feed_item_id=item_id)
        assert {row["type"] for row in rows} == {
            "important",
            "not_relevant",
            "follow",
            "already_knew",
            "learned_now",
            "less_like_this",
            "undo",
        }
        assert all(row["event_id"] and row["delta_id"] for row in rows)


def test_expanded_signals_do_not_break_important_not_relevant_rebuild(database: Database) -> None:
    item_id, _event_id = _project_statuspage_item(database)
    store = FeedStore(database)
    store.save_feedback("learner", item_id, "important")
    store.save_feedback("learner", item_id, "important")
    store.save_feedback("learner", item_id, "already_knew")
    store.save_feedback("learner", item_id, "follow")
    store.save_feedback("learner", item_id, "less_like_this")

    with database.connect() as connection:
        apply_feedback_ranking(connection, user_id="learner")
        features = connection.execute(
            """
            SELECT important_count, not_relevant_count, follow_count,
                   already_knew_count, learned_now_count, less_like_this_count
            FROM user_ranking_features
            WHERE user_id = 'learner'
            """
        ).fetchone()
        assert features["important_count"] == 1
        assert features["not_relevant_count"] == 0
        assert features["follow_count"] == 1
        assert features["already_knew_count"] == 1
        assert features["learned_now_count"] == 0
        assert features["less_like_this_count"] == 1
