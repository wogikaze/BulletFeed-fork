from app.services.feed_projection import FeedProjector
from app.services.github_release_pipeline import ingest_github_release_events
from app.services.ledger_projection import LedgerProjector
from app.services.rss_pipeline import ingest_feed_events
from app.services.statuspage_pipeline import StatuspagePipeline


def _summary():
    return {
        "incidents": [
            {
                "id": "inc_1",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_1",
                "incident_updates": [
                    {
                        "id": "upd_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    },
                    {
                        "id": "upd_2",
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


def test_feed_projection_creates_one_item_per_novel_delta(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")

    item_ids = FeedProjector(database).project_event_for_user(user_id="user_1", event_id=event_id)

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM feed_items WHERE user_id = 'user_1' AND event_id = ? ORDER BY updated_at",
            (event_id,),
        ).fetchall()
    assert len(rows) == 2
    assert len(item_ids) == 2
    assert all(row["relation_level"] == "reference" for row in rows)
    assert [row["importance_level"] for row in rows] == ["medium", "medium"]
    assert [row["importance_confidence"] for row in rows] == ["medium", "high"]


def test_feed_projection_is_idempotent(database):
    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")

    projector = FeedProjector(database)
    first = projector.project_event_for_user(user_id="user_1", event_id=event_id)
    second = projector.project_event_for_user(user_id="user_1", event_id=event_id)

    assert second == first
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchone()["count"]
    assert count == 2


def _plant_unrelated_event(database, event_id: str = "unrelated_noise") -> str:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO events (
                id, title, summary, current_phase, current_summary,
                current_since, current_confidence, updated_at
            ) VALUES (?, 'Horticulture soil notes', 'Garden pH commentary.',
                      'identified', 'soil notes', '2026-08-01T00:00:00Z',
                      'low', '2026-08-01T00:00:00Z')
            """,
            (event_id,),
        )
    return event_id


def _ingest_kotlin_source(database) -> str:
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
    return result.event_ids[0]


def _record_projected_events(monkeypatch, projector: FeedProjector) -> list[str]:
    seen: list[str] = []
    original = projector.project_event_for_user

    def _wrapped(*, user_id: str, event_id: str):
        seen.append(event_id)
        return original(user_id=user_id, event_id=event_id)

    monkeypatch.setattr(projector, "project_event_for_user", _wrapped)
    return seen


def test_reproject_user_skips_unrelated_planted_event(database, monkeypatch):
    kotlin_event_id = _ingest_kotlin_source(database)
    unrelated_id = _plant_unrelated_event(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")
        connection.execute(
            """
            INSERT INTO topics (
                id, user_id, name, type, priority, sort_order, created_at
            ) VALUES ('topic_kotlin', 'user_1', 'Kotlin', 'technology', 'high', 0, 0)
            """
        )

    projector = FeedProjector(database)
    seen = _record_projected_events(monkeypatch, projector)
    projector.reproject_user(user_id="user_1")

    assert unrelated_id not in seen
    assert kotlin_event_id in seen
    with database.connect() as connection:
        unrelated_items = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (unrelated_id,),
        ).fetchone()["count"]
        kotlin_items = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (kotlin_event_id,),
        ).fetchone()["count"]
    assert unrelated_items == 0
    assert kotlin_items >= 1


def test_reproject_user_surfaces_source_changes_after_adding_topic(database):
    event_id = _ingest_kotlin_source(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")

    projector = FeedProjector(database)
    projector.reproject_user(user_id="user_1")
    with database.connect() as connection:
        before = connection.execute(
            "SELECT COUNT(*) AS count FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchone()["count"]
    assert before == 0

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO topics (
                id, user_id, name, type, priority, sort_order, created_at
            ) VALUES ('topic_kotlin', 'user_1', 'Kotlin', 'technology', 'high', 0, 0)
            """
        )
    projector.reproject_user(user_id="user_1")

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT relation_level, matched_topics_json
            FROM feed_items WHERE user_id = 'user_1' AND event_id = ?
            """,
            (event_id,),
        ).fetchall()
    assert rows
    assert all(row["relation_level"] == "adjacent" for row in rows)
    assert all("Kotlin" in row["matched_topics_json"] for row in rows)


def test_reproject_user_includes_selected_repository_events(database, monkeypatch):
    unrelated_id = _plant_unrelated_event(database)
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
    release_event_id = result.event_ids[0]

    projector = FeedProjector(database)
    seen = _record_projected_events(monkeypatch, projector)
    projector.reproject_user(user_id="user_1")

    assert unrelated_id not in seen
    assert release_event_id in seen


def test_reproject_user_updates_relation_on_remaining_items(database):
    event_id = _ingest_kotlin_source(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")

    projector = FeedProjector(database)
    projector.project_event_for_user(user_id="user_1", event_id=event_id)
    with database.connect() as connection:
        before = connection.execute(
            """
            SELECT relation_level, personalization_rank
            FROM feed_items WHERE user_id = 'user_1' AND event_id = ?
            """,
            (event_id,),
        ).fetchall()
    assert before
    assert all(row["relation_level"] == "reference" for row in before)

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO topics (
                id, user_id, name, type, priority, sort_order, created_at
            ) VALUES ('topic_kotlin', 'user_1', 'Kotlin', 'technology', 'high', 0, 0)
            """
        )
    projector.reproject_user(user_id="user_1")

    with database.connect() as connection:
        after = connection.execute(
            """
            SELECT relation_level, relation_reason, matched_topics_json, personalization_rank
            FROM feed_items WHERE user_id = 'user_1' AND event_id = ?
            """,
            (event_id,),
        ).fetchall()
    assert after
    assert all(row["relation_level"] == "adjacent" for row in after)
    assert all(row["personalization_rank"] > 0 for row in after)
    assert all("Kotlin" in row["matched_topics_json"] for row in after)


def test_reproject_user_dismisses_unmatched_reference_when_follow_empty(database):
    event_id = _ingest_kotlin_source(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_1', 0)")

    projector = FeedProjector(database)
    projector.project_event_for_user(user_id="user_1", event_id=event_id)
    projector.reproject_user(user_id="user_1")

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT dismissed, relation_level FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchall()
    assert rows
    assert all(row["relation_level"] == "reference" for row in rows)
    assert all(row["dismissed"] == 1 for row in rows)

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO topics (
                id, user_id, name, type, priority, sort_order, created_at
            ) VALUES ('topic_android', 'user_1', 'Android', 'technology', 'normal', 0, 0)
            """
        )
    projector.reproject_user(user_id="user_1")

    with database.connect() as connection:
        undismissed = connection.execute(
            "SELECT dismissed, relation_level FROM feed_items WHERE user_id = 'user_1' AND event_id = ?",
            (event_id,),
        ).fetchall()
    assert all(row["relation_level"] == "reference" for row in undismissed)
    assert all(row["dismissed"] == 0 for row in undismissed)
