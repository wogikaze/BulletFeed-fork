from pathlib import Path

from fastapi.testclient import TestClient

from app.database import Database
from app.services.event_access import revoke_repository_access
from app.services.github_release_pipeline import ingest_github_release_events
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.event_search_store import EventSearchStore


def _project_history_only_event(database: Database) -> str:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="history-search-test",
        summary={
            "incidents": [
                {
                    "id": "inc_history_search",
                    "name": "Historical edge cache regression",
                    "impact": "minor",
                    "created_at": "2026-08-20T00:00:00Z",
                    "shortlink": "https://stspg.io/inc_history_search",
                    "incident_updates": [
                        {
                            "id": "upd_history_search_1",
                            "status": "resolved",
                            "body": "Unique archive needle: cache headers normalized.",
                            "display_at": "2026-08-20T00:30:00Z",
                            "updated_at": "2026-08-20T00:30:00Z",
                        }
                    ],
                }
            ]
        },
        retrieved_at="2026-08-20T00:31:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    return event_id


def test_event_search_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/events/search", params={"q": "runtime"})
    assert response.status_code == 401


def test_event_search_finds_history_outside_loaded_feed(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    event_id = _project_history_only_event(database)
    feed = client.get("/v1/feed", headers=auth_headers).json()["items"]
    assert all(item["eventId"] != event_id for item in feed)

    response = client.get(
        "/v1/events/search",
        headers=auth_headers,
        params={"q": "archive needle"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [event_id]
    assert body["items"][0]["currentPhase"] == "resolved"
    assert body["items"][0]["sourcePublisher"]


def test_event_search_cursor_is_stable_and_duplicate_free(tmp_path: Path) -> None:
    database = Database(tmp_path / "event-search-pagination.db")
    database.initialize()
    store = EventSearchStore(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('user', 0)")
        for index in range(4):
            connection.execute(
                """
                INSERT INTO events (
                    id, title, summary, current_phase, current_summary,
                    current_since, current_confidence, updated_at
                ) VALUES (?, ?, ?, 'resolved', ?, ?, 'high', ?)
                """,
                (
                    f"evt-{index}",
                    f"Searchable event {index}",
                    f"summary {index}",
                    f"state {index}",
                    f"2026-08-20T00:0{index}:00Z",
                    f"2026-08-20T00:0{index}:00Z",
                ),
            )

    first, cursor = store.search("user", query="", cursor=None, limit=2)
    assert [item.id for item in first] == ["evt-3", "evt-2"]
    assert cursor is not None
    second, final_cursor = store.search("user", query="", cursor=cursor, limit=2)
    assert [item.id for item in second] == ["evt-1", "evt-0"]
    assert final_cursor is None
    assert {item.id for item in first}.isdisjoint(item.id for item in second)


def test_event_search_private_visibility_is_fail_closed(tmp_path: Path) -> None:
    database = Database(tmp_path / "private-event-search.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('owner', 0), ('other', 0)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, html_url, selected, private
            ) VALUES ('owner', 'repo-1', 'acme/private', 'https://github.com/acme/private', 1, 1)
            """
        )

    result = ingest_github_release_events(
        database,
        owner="acme",
        repository="private",
        releases=[
            {
                "id": 42,
                "tag_name": "v1.0.0",
                "name": "Private release",
                "html_url": "https://github.com/acme/private/releases/tag/v1.0.0",
                "published_at": "2026-08-22T10:00:00Z",
                "updated_at": "2026-08-22T10:00:00Z",
                "draft": False,
                "prerelease": False,
                "body": "Internal release notes.",
            }
        ],
        retrieved_at="2026-08-22T10:01:00Z",
    )
    event_id = result.event_ids[0]
    store = EventSearchStore(database)

    owner, _ = store.search("owner", query="Private release", cursor=None, limit=20)
    other, _ = store.search("other", query="Private release", cursor=None, limit=20)
    assert [item.id for item in owner] == [event_id]
    assert other == []

    revoke_repository_access(database, user_id="owner", repository_key="acme/private")
    revoked, _ = store.search("owner", query="Private release", cursor=None, limit=20)
    assert revoked == []


def test_event_search_rejects_invalid_cursor(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        "/v1/events/search",
        headers=auth_headers,
        params={"cursor": "not-a-valid-cursor"},
    )
    assert response.status_code == 422
