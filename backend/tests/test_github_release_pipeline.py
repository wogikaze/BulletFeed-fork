import json
from pathlib import Path

from app.database import Database
from app.services.github_release_pipeline import ingest_github_release_events


def _release(body: str, updated_at: str) -> dict:
    return {
        "id": 42,
        "tag_name": "v2.0.0",
        "name": "Widget 2.0",
        "html_url": "https://github.com/acme/widget/releases/tag/v2.0.0",
        "created_at": "2026-08-20T10:00:00Z",
        "published_at": "2026-08-20T10:00:00Z",
        "updated_at": updated_at,
        "draft": False,
        "prerelease": False,
        "body": body,
    }


def test_github_release_revisions_reach_watched_user_feed(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected
            ) VALUES ('user_1', '42', 'acme/widget', 'https://github.com/acme/widget', 1)
            """
        )

    first = ingest_github_release_events(
        database,
        owner="acme",
        repository="widget",
        releases=[_release("Initial notes.", "2026-08-20T10:01:00Z")],
        retrieved_at="2026-08-20T10:02:00Z",
    )
    second = ingest_github_release_events(
        database,
        owner="acme",
        repository="widget",
        releases=[_release("Initial notes plus migration guidance.", "2026-08-20T11:00:00Z")],
        retrieved_at="2026-08-20T11:01:00Z",
    )

    assert first.event_ids == second.event_ids
    event_id = first.event_ids[0]
    with database.connect() as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        deltas = connection.execute(
            "SELECT * FROM deltas WHERE event_id = ? AND active = 1 ORDER BY occurred_at, id",
            (event_id,),
        ).fetchall()
        sources = connection.execute(
            "SELECT * FROM event_sources WHERE event_id = ? ORDER BY retrieved_at, id",
            (event_id,),
        ).fetchall()
        feed = connection.execute(
            """
            SELECT * FROM feed_items
            WHERE user_id = 'user_1' AND event_id = ?
            ORDER BY updated_at, id
            """,
            (event_id,),
        ).fetchall()

    assert event["current_phase"] == "released"
    assert event["current_summary"] == "Initial notes plus migration guidance."
    assert [row["type"] for row in deltas] == ["new_fact", "detail"]
    assert {row["kind"] for row in sources} == {"github_release"}
    assert {row["publisher"] for row in sources} == {"GitHub"}
    assert len(feed) == 2
    assert all(row["relation_level"] == "direct" for row in feed)
    assert all(
        json.loads(row["matched_repos_json"])
        == [{"id": "42", "name": "acme/widget", "url": "https://github.com/acme/widget"}]
        for row in feed
    )


def test_github_release_same_payload_reuses_observation_without_new_delta(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    release = _release("Initial notes.", "2026-08-20T10:01:00Z")

    first = ingest_github_release_events(
        database,
        owner="acme",
        repository="widget",
        releases=[release],
        retrieved_at="2026-08-20T10:02:00Z",
    )
    second = ingest_github_release_events(
        database,
        owner="acme",
        repository="widget",
        releases=[release],
        retrieved_at="2026-08-20T10:03:00Z",
    )

    assert first.event_ids == second.event_ids
    with database.connect() as connection:
        observations = connection.execute("SELECT id FROM observations").fetchall()
        deltas = connection.execute(
            "SELECT id, type FROM deltas WHERE event_id = ? AND active = 1",
            (first.event_ids[0],),
        ).fetchall()

    assert len(observations) == 1
    assert [row["type"] for row in deltas] == ["new_fact"]
