from pathlib import Path

from app.database import Database
from app.services.json_feed import normalize_json_feed
from app.services.json_feed_pipeline import ingest_json_feed_events
from app.services.source_subscriptions import add_subscription_user


def _feed(summary: str, modified: str) -> dict:
    return {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "Acme Engineering",
        "feed_url": "https://engineering.acme.example/feed.json",
        "items": [
            {
                "id": "widget-migration",
                "url": "https://engineering.acme.example/widget-migration",
                "title": "Widget migration guide",
                "summary": summary,
                "content_html": "<p>fallback <strong>content</strong></p>",
                "date_published": "2026-08-20T10:00:00Z",
                "date_modified": modified,
            }
        ],
    }


def test_json_feed_normalization_strips_markup_and_preserves_canonical_identity() -> None:
    observations = normalize_json_feed(
        _feed("Migration <b>guidance</b>.", "2026-08-20T10:01:00Z"),
        feed_url="https://engineering.acme.example/feed.json",
    )

    assert len(observations) == 1
    assert observations[0].source_type == "json_feed"
    assert observations[0].source_observation_id == "widget-migration"
    assert observations[0].payload["summary"] == "Migration guidance."


def test_json_feed_entry_revisions_reach_public_event_projection(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    first = ingest_json_feed_events(
        database,
        feed=_feed("Initial migration guidance.", "2026-08-20T10:01:00Z"),
        feed_url="https://engineering.acme.example/feed.json",
        retrieved_at="2026-08-20T10:02:00Z",
    )
    second = ingest_json_feed_events(
        database,
        feed=_feed("Migration guidance now covers rollback.", "2026-08-20T11:00:00Z"),
        feed_url="https://engineering.acme.example/feed.json",
        retrieved_at="2026-08-20T11:01:00Z",
    )

    assert first.event_ids == second.event_ids
    event_id = first.event_ids[0]
    with database.connect() as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        deltas = connection.execute(
            "SELECT * FROM deltas WHERE event_id = ? ORDER BY occurred_at, id",
            (event_id,),
        ).fetchall()
        sources = connection.execute(
            "SELECT * FROM event_sources WHERE event_id = ? ORDER BY retrieved_at, id",
            (event_id,),
        ).fetchall()

    assert event["current_phase"] == "published"
    assert event["current_summary"] == "Migration guidance now covers rollback."
    assert [row["type"] for row in deltas] == ["new_fact", "detail"]
    assert {row["kind"] for row in sources} == {"json_feed"}
    assert {row["publisher"] for row in sources} == {"engineering.acme.example"}


def test_json_feed_same_entry_refetch_keeps_observation_id(tmp_path: Path) -> None:
    database = Database(tmp_path / "json-idempotent.db")
    database.initialize()
    feed = _feed("Initial migration guidance.", "2026-08-20T10:01:00Z")

    ingest_json_feed_events(
        database,
        feed=feed,
        feed_url="https://engineering.acme.example/feed.json",
        retrieved_at="2026-08-20T10:02:00Z",
    )
    ingest_json_feed_events(
        database,
        feed=feed,
        feed_url="https://engineering.acme.example/feed.json",
        retrieved_at="2026-08-20T10:03:00Z",
    )

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT id FROM observations ORDER BY retrieved_at, id"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["id"].startswith("obs_")


def test_json_feed_ingest_projects_feed_for_subscribed_users_only(tmp_path: Path) -> None:
    database = Database(tmp_path / "json-audience.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO users (id, created_at) VALUES ('user_a', 0), ('user_outsider', 0)"
        )
    add_subscription_user(
        database,
        source_type="json_feed",
        source_key="https://engineering.acme.example/feed.json",
        user_id="user_a",
    )

    result = ingest_json_feed_events(
        database,
        feed=_feed("Initial migration guidance.", "2026-08-20T10:01:00Z"),
        feed_url="https://engineering.acme.example/feed.json",
        retrieved_at="2026-08-20T10:02:00Z",
    )

    with database.connect() as connection:
        audience = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_a' AND event_id = ?",
            (result.event_ids[0],),
        ).fetchone()["count"]
        outsider = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_outsider'"
        ).fetchone()["count"]
        exposures = connection.execute("SELECT COUNT(*) AS count FROM user_claim_exposures").fetchone()[
            "count"
        ]
    assert audience >= 1
    assert outsider == 0
    assert exposures == 0
