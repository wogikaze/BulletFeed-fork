from app.services.github_release_pipeline import ingest_github_release_events
from app.services.osv_pipeline import ingest_osv_events
from app.services.rss_pipeline import ingest_feed_events
from app.stores.event_store import EventStore


def test_event_detail_accepts_source_specific_release_state(database) -> None:
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

    event = EventStore(database).get_event("contract-user", result.event_ids[0], None)
    assert event.current_state.phase == "released"
    assert event.sources[0].kind == "github_release"


def test_event_detail_accepts_source_specific_security_state(database) -> None:
    result = ingest_osv_events(
        database,
        ecosystem="PyPI",
        package="example",
        version="1.0.0",
        vulnerabilities=[
            {
                "id": "OSV-2026-1",
                "summary": "Example vulnerability",
                "details": "Affected before 2.0.0.",
                "published": "2026-08-22T00:00:00Z",
                "modified": "2026-08-22T00:00:00Z",
            }
        ],
        retrieved_at="2026-08-22T00:01:00Z",
    )

    event = EventStore(database).get_event("contract-user", result.event_ids[0], None)
    assert event.current_state.phase == "affected"
    assert event.sources[0].kind == "osv"


def test_event_detail_accepts_rss_atom_source_kind(database) -> None:
    result = ingest_feed_events(
        database,
        preview={
            "source_url": "https://example.com/feed.xml",
            "items": [
                {
                    "title": "API migration guide",
                    "link": "https://example.com/changelog/migration",
                    "published": "2026-08-22T00:00:00Z",
                    "summary": "Migration deadline announced.",
                }
            ],
        },
        retrieved_at="2026-08-22T00:01:00Z",
    )

    event = EventStore(database).get_event("contract-user", result.event_ids[0], None)
    assert event.current_state.phase == "published"
    assert event.sources[0].kind == "rss_atom"
