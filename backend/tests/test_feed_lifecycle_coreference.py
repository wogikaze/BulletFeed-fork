from app.services.feed_lifecycle import resolve_feed_lifecycle
from app.services.rss_pipeline import ingest_feed_events


def test_explicit_retirement_titles_share_publisher_event_identity() -> None:
    announced = resolve_feed_lifecycle(
        "GitHub Models is being fully retired on July 30, 2026",
        "https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/",
    )
    retired = resolve_feed_lifecycle(
        "GitHub Models is now retired",
        "https://github.blog/changelog/2026-07-30-github-models-is-now-retired/",
    )
    spark = resolve_feed_lifecycle(
        "Upcoming deprecation of GitHub Spark on github.com",
        "https://github.blog/changelog/2026-08-04-upcoming-deprecation-of-github-spark-on-github-com/",
    )

    assert announced is not None
    assert retired is not None
    assert spark is not None
    assert announced.canonical_event_key == retired.canonical_event_key
    assert announced.state == "retirement_announced"
    assert retired.state == "retired"
    assert spark.canonical_event_key != announced.canonical_event_key
    assert spark.state == "deprecation_announced"


def test_generic_similar_feed_titles_prefer_false_split() -> None:
    assert resolve_feed_lifecycle(
        "GitHub Models adds a new playground feature",
        "https://github.blog/changelog/example-a/",
    ) is None
    assert resolve_feed_lifecycle(
        "GitHub Models migration guide",
        "https://github.blog/changelog/example-b/",
    ) is None


def test_rss_retirement_announcement_and_completion_form_state_transition(database) -> None:
    preview = {
        "title": "GitHub Changelog",
        "source_url": "https://github.blog/changelog/feed/",
        "items": [
            {
                "title": "GitHub Models is being fully retired on July 30, 2026",
                "link": "https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/",
                "published": "2026-07-01T00:00:00Z",
                "summary": "GitHub Models will be fully retired on July 30, 2026.",
            },
            {
                "title": "GitHub Models is now retired",
                "link": "https://github.blog/changelog/2026-07-30-github-models-is-now-retired/",
                "published": "2026-07-30T00:00:00Z",
                "summary": "GitHub Models is now retired for all customers.",
            },
            {
                "title": "Upcoming deprecation of GitHub Spark on github.com",
                "link": "https://github.blog/changelog/2026-08-04-upcoming-deprecation-of-github-spark-on-github-com/",
                "published": "2026-08-04T00:00:00Z",
                "summary": "Existing users can access GitHub Spark until August 31, 2026.",
            },
        ],
    }

    result = ingest_feed_events(
        database,
        preview=preview,
        retrieved_at="2026-08-22T12:40:00Z",
    )

    assert len(result.claim_ids) == 3
    assert len(result.event_ids) == 2

    with database.connect() as connection:
        models_event = connection.execute(
            "SELECT * FROM events WHERE title = 'GitHub Models'"
        ).fetchone()
        models_deltas = connection.execute(
            "SELECT type, before_text, after_text FROM deltas "
            "WHERE event_id = ? AND active = 1 ORDER BY occurred_at, id",
            (models_event["id"],),
        ).fetchall()
        spark_event = connection.execute(
            "SELECT * FROM events WHERE title = 'GitHub Spark'"
        ).fetchone()

    assert models_event["current_phase"] == "retired"
    assert models_event["current_since"] == "2026-07-30T00:00:00Z"
    assert [row["type"] for row in models_deltas] == ["new_fact", "state_update"]
    assert models_deltas[-1]["before_text"] == "retirement_announced"
    assert models_deltas[-1]["after_text"] == "retired"
    assert spark_event["current_phase"] == "deprecation_announced"
