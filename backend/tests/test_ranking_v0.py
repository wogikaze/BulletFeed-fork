from app.services.feed_projection import FeedProjector
from app.services.github_release_pipeline import ingest_github_release_events
from app.services.ranking import evaluate_importance


def test_importance_is_deterministic_and_separate_from_relation() -> None:
    security = evaluate_importance(source_type="osv", delta_type="new_fact")
    correction = evaluate_importance(source_type="rss_atom", delta_type="correction")
    release = evaluate_importance(source_type="github_release", delta_type="detail")

    assert security.level == "high"
    assert correction.level == "high"
    assert release.level == "medium"
    assert all(decision.confidence != "low" for decision in (security, correction, release))


def test_feed_projection_replaces_placeholder_importance(database) -> None:
    result = ingest_github_release_events(
        database,
        owner="acme",
        repository="sdk",
        releases=[
            {
                "id": 101,
                "tag_name": "v2.0.0",
                "name": "SDK 2.0.0",
                "body": "Stable release.",
                "draft": False,
                "prerelease": False,
                "html_url": "https://github.com/acme/sdk/releases/tag/v2.0.0",
                "published_at": "2026-08-22T00:00:00Z",
                "created_at": "2026-08-22T00:00:00Z",
                "updated_at": "2026-08-22T00:00:00Z",
            }
        ],
        retrieved_at="2026-08-22T00:01:00Z",
    )
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user_rank', 0)")

    FeedProjector(database).project_event_for_user(
        user_id="user_rank",
        event_id=result.event_ids[0],
    )

    with database.connect() as connection:
        item = connection.execute(
            "SELECT importance_level, importance_reason, importance_confidence FROM feed_items "
            "WHERE user_id = 'user_rank'"
        ).fetchone()

    assert item["importance_level"] == "medium"
    assert item["importance_confidence"] == "high"
    assert "personalized importance is not evaluated" not in item["importance_reason"]
