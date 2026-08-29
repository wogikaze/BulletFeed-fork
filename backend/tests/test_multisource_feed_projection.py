import json
from pathlib import Path

from app.database import Database
from app.services.feed_projection import FeedProjector
from app.services.github_release_pipeline import ingest_github_release_events
from app.services.rss_pipeline import ingest_feed_events
from app.stores.feed_store import FeedStore


def test_github_release_feed_uses_typed_repo_relation_through_api_contract(tmp_path: Path) -> None:
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

    result = ingest_github_release_events(
        database,
        owner="acme",
        repository="widget",
        releases=[
            {
                "id": 42,
                "tag_name": "v2.0.0",
                "name": "Widget 2.0",
                "html_url": "https://github.com/acme/widget/releases/tag/v2.0.0",
                "created_at": "2026-08-20T10:00:00Z",
                "published_at": "2026-08-20T10:00:00Z",
                "updated_at": "2026-08-20T10:01:00Z",
                "draft": False,
                "prerelease": False,
                "body": "Migration guidance.",
            }
        ],
        retrieved_at="2026-08-20T10:02:00Z",
    )
    event_id = result.event_ids[0]

    FeedProjector(database).project_event_for_user(user_id="user_1", event_id=event_id)

    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchone()

    assert row["relation_level"] == "direct"
    assert json.loads(row["matched_repos_json"]) == [
        {
            "id": "42",
            "name": "acme/widget",
            "url": "https://github.com/acme/widget",
        }
    ]
    assert row["importance_reason"] == "A tracked software release changed."

    items, _ = FeedStore(database).list_feed(
        "user_1",
        relation="direct",
        item_status=None,
        cursor=None,
        limit=20,
    )
    assert len(items) == 1
    assert items[0].relation.matched_repositories[0].id == "42"
    assert items[0].relation.matched_repositories[0].name == "acme/widget"


def test_rss_feed_matches_user_topic_as_adjacent_relation(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
        connection.execute(
            """
            INSERT INTO topics (
                id, user_id, name, type, priority, sort_order, created_at
            ) VALUES ('topic_kotlin', 'user_1', 'Kotlin', 'technology', 'high', 0, 0)
            """
        )

    result = ingest_feed_events(
        database,
        preview={
            "title": "Acme Engineering",
            "source_url": "https://engineering.acme.example/feed.xml",
            "items": [
                {
                    "title": "Kotlin 2.3 migration guide",
                    "link": "https://engineering.acme.example/kotlin-2-3",
                    "published": "2026-08-20T15:00:00Z",
                    "updated": "2026-08-20T15:00:00Z",
                    "summary": "Kotlin compiler migration guidance.",
                }
            ],
        },
        retrieved_at="2026-08-20T15:01:00Z",
    )
    event_id = result.event_ids[0]

    FeedProjector(database).project_event_for_user(user_id="user_1", event_id=event_id)

    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchone()

    assert row["relation_level"] == "adjacent"
    assert json.loads(row["matched_topics_json"]) == ["Kotlin"]
    assert json.loads(row["matched_repos_json"]) == []
    assert "Kotlin" in row["relation_reason"]
    assert "relation-features-v01" in row["relation_reason"]
