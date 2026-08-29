from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.database import Database
from app.db.migrations import KNOWN_REVISIONS
from app.services.feed_projection import FeedProjector
from app.services.feedback_signals import assert_feedback_does_not_mutate_ledger, ledger_world_state
from app.services.ledger_projection import LedgerProjector
from app.services.session_telemetry import (
    KIND_CARD_DISPLAYED,
    KIND_FEEDBACK,
    KIND_SESSION_START,
    list_session_outcomes,
    prune_expired_telemetry,
    record_session_outcome,
    reset_session_telemetry,
    start_feed_session,
    summarize_session_metrics,
)
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore


def _summary() -> dict:
    return {
        "incidents": [
            {
                "id": "inc_session_telemetry",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_session_telemetry",
                "incident_updates": [
                    {
                        "id": "upd_st_1",
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


def _project_item(database: Database, *, user_id: str) -> str:
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
    items, _ = FeedStore(database).list_feed(user_id, relation=None, item_status=None, cursor=None, limit=5)
    assert items
    return items[0].id


def test_get_feed_does_not_start_session(database: Database) -> None:
    _project_item(database, user_id="learner")
    with database.connect() as connection:
        assert list_session_outcomes(connection, user_id="learner") == ()


def test_session_metrics_and_reset_do_not_touch_ledger(database: Database) -> None:
    item_id = _project_item(database, user_id="learner")
    with database.connect() as connection:
        before = ledger_world_state(connection)
        session = start_feed_session(connection, user_id="learner", created_at=100)
        assert session is not None
        record_session_outcome(
            connection,
            user_id="learner",
            kind=KIND_CARD_DISPLAYED,
            feed_item_id=item_id,
            created_at=101,
        )
        record_session_outcome(
            connection,
            user_id="learner",
            kind=KIND_FEEDBACK,
            feed_item_id=item_id,
            feedback_type="learned_now",
            created_at=102,
        )
        metrics = summarize_session_metrics(list_session_outcomes(connection, user_id="learner"))
        assert metrics.session_count == 1
        assert metrics.displayed_count == 1
        assert metrics.useful_card_rate == 1.0
        assert metrics.already_known_reshow_rate == 0.0
        assert metrics.cards_to_useful_item == 1.0
        assert metrics.feedback_response_rate == 1.0
        reset_session_telemetry(connection, user_id="learner")
        after = ledger_world_state(connection)
        assert_feedback_does_not_mutate_ledger(before, after)
        assert list_session_outcomes(connection, user_id="learner") == ()


def test_disabled_telemetry_does_not_break_feed(database: Database, monkeypatch) -> None:
    monkeypatch.setenv("BULLETFEED_SESSION_TELEMETRY_ENABLED", "false")
    get_settings.cache_clear()
    try:
        item_id = _project_item(database, user_id="learner")
        disabled = Settings(session_telemetry_enabled=False)
        with database.connect() as connection:
            assert start_feed_session(connection, user_id="learner", settings=disabled) is None
            assert (
                record_session_outcome(
                    connection,
                    user_id="learner",
                    kind=KIND_CARD_DISPLAYED,
                    feed_item_id=item_id,
                    settings=disabled,
                )
                is None
            )
            assert list_session_outcomes(connection, user_id="learner") == ()
        items, _ = FeedStore(database).list_feed(
            "learner", relation=None, item_status=None, cursor=None, limit=5
        )
        assert items
    finally:
        get_settings.cache_clear()


def test_tenant_isolation_and_http_surface(client: TestClient, database: Database) -> None:
    first = client.post("/v1/sessions").json()
    second = client.post("/v1/sessions").json()
    headers_a = {"Authorization": f"Bearer {first['accessToken']}"}
    headers_b = {"Authorization": f"Bearer {second['accessToken']}"}
    item_id = _project_item(database, user_id=first["userId"])

    started = client.post("/v1/me/feed-sessions", headers=headers_a)
    assert started.status_code == 201
    session_id = started.json()["id"]
    assert session_id.startswith("fs_")

    with database.connect() as connection:
        record_session_outcome(
            connection,
            user_id=first["userId"],
            kind=KIND_CARD_DISPLAYED,
            feed_item_id=item_id,
        )
        connection.commit()
    FeedStore(database).save_feedback(first["userId"], item_id, "already_knew")
    metrics = client.get("/v1/me/feed-sessions/metrics", headers=headers_a)
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["sessionCount"] == 1
    assert body["alreadyKnownReshowRate"] == 1.0

    other = client.get("/v1/me/feed-sessions/metrics", headers=headers_b)
    assert other.json()["sessionCount"] == 0

    ended = client.post(f"/v1/me/feed-sessions/{session_id}/end", headers=headers_a)
    assert ended.status_code == 200
    stolen = client.post(f"/v1/me/feed-sessions/{session_id}/end", headers=headers_b)
    assert stolen.status_code == 404

    deleted = client.delete("/v1/me/feed-sessions", headers=headers_a)
    assert deleted.status_code == 204
    after = client.get("/v1/me/feed-sessions/metrics", headers=headers_a)
    assert after.json()["sessionCount"] == 0


def test_outcomes_never_store_scroll_coordinates(database: Database) -> None:
    item_id = _project_item(database, user_id="learner")
    with database.connect() as connection:
        start_feed_session(connection, user_id="learner")
        record_session_outcome(
            connection,
            user_id="learner",
            kind=KIND_CARD_DISPLAYED,
            feed_item_id=item_id,
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(feed_session_outcomes)")}
    assert "dwell_ms" not in columns
    assert "visible_ratio" not in columns
    assert "x" not in columns
    assert "y" not in columns


def test_revision_16_adds_telemetry_tables_without_touching_ledger(tmp_path: Path) -> None:
    database = Database(tmp_path / "pre-telemetry.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id = '16'")
        connection.execute("DROP TABLE IF EXISTS feed_session_outcomes")
        connection.execute("DROP TABLE IF EXISTS feed_sessions")
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_a', 0)")
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (
                'obs_tel', 'statuspage', 'abcd1234', 'inc_tel',
                'hash', '{}', 'https://example.test', '2026-08-22T00:00:00Z'
            )
            """
        )
        before = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    database.initialize()
    with database.connect() as connection:
        revisions = {row[0] for row in connection.execute("SELECT revision_id FROM schema_migrations")}
        assert revisions == set(KNOWN_REVISIONS)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'feed_sessions'"
        ).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == before
        assert prune_expired_telemetry(connection, now=0) == 0


def test_missing_session_skips_outcome_without_ledger_write(database: Database) -> None:
    item_id = _project_item(database, user_id="learner")
    with database.connect() as connection:
        before = ledger_world_state(connection)
        assert (
            record_session_outcome(
                connection,
                user_id="learner",
                kind=KIND_CARD_DISPLAYED,
                feed_item_id=item_id,
            )
            is None
        )
        after = ledger_world_state(connection)
        assert_feedback_does_not_mutate_ledger(before, after)
        assert KIND_SESSION_START not in {
            row.kind for row in list_session_outcomes(connection, user_id="learner")
        }
