from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.database import Database
from app.services.event_access import revoke_repository_access
from app.services.feed_projection import FeedProjector
from app.services.github_release_pipeline import ingest_github_release_events
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.event_store import EventStore, _fact_texts


def test_fact_texts_split_source_sentences() -> None:
    assert _fact_texts("First change. Second change.", "") == ("First change.", "Second change.")
    assert _fact_texts("調査を開始した。原因を特定した。", "") == ("調査を開始した。", "原因を特定した。")
    assert _fact_texts("published", "published") == ("published",)


def _project_test_event(database: Database) -> tuple[str, str]:
    result = StatuspagePipeline(database).ingest_summary(
        page_id="events-test",
        summary={
            "incidents": [
                {
                    "id": "inc_events",
                    "name": "Workers runtime incident",
                    "impact": "major",
                    "created_at": "2026-08-22T00:00:00Z",
                    "shortlink": "https://stspg.io/inc_events",
                    "incident_updates": [
                        {
                            "id": "upd_events_1",
                            "status": "investigating",
                            "body": "Investigating elevated errors.",
                            "display_at": "2026-08-22T00:00:00Z",
                            "updated_at": "2026-08-22T00:00:00Z",
                        },
                        {
                            "id": "upd_events_2",
                            "status": "identified",
                            "body": "Runtime saturation identified.",
                            "display_at": "2026-08-22T00:10:00Z",
                            "updated_at": "2026-08-22T00:10:00Z",
                        },
                    ],
                }
            ]
        },
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    LedgerProjector(database).project_event(event_id)
    with database.connect() as connection:
        user_id = connection.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    FeedProjector(database).project_event_for_user(user_id=user_id, event_id=event_id)
    return event_id, user_id


def test_private_repository_event_is_not_a_cross_user_idor(tmp_path: Path) -> None:
    database = Database(tmp_path / "private-event.db")
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
    store = EventStore(database)

    assert store.get_event("owner", event_id, None).id == event_id
    with pytest.raises(HTTPException) as denied:
        store.get_event("other", event_id, None)
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as follow_denied:
        store.set_following("other", event_id, True)
    assert follow_denied.value.status_code == 404

    revoke_repository_access(database, user_id="owner", repository_key="acme/private")
    with pytest.raises(HTTPException) as revoked:
        store.get_event("owner", event_id, None)
    assert revoked.value.status_code == 404
    with database.connect() as connection:
        feed = connection.execute(
            "SELECT dismissed FROM feed_items WHERE user_id = 'owner' AND event_id = ?",
            (event_id,),
        ).fetchone()
    assert feed["dismissed"] == 1


def test_event_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/events/missing")
    assert response.status_code == 401


def test_event_detail_and_opened_delta(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    missing = client.get("/v1/events/missing", headers=auth_headers)
    assert missing.status_code == 404
    event_id, _ = _project_test_event(database)

    feed_item = next(
        item
        for item in client.get("/v1/feed", headers=auth_headers).json()["items"]
        if item["eventId"] == event_id
    )
    detail = client.get(
        f"/v1/events/{event_id}",
        headers=auth_headers,
        params={"fromFeedItem": feed_item["id"]},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["currentState"]["phase"] == "identified"
    assert body["latestDelta"]["type"] == "state_update"
    assert body["openedDelta"]["id"] == feed_item["delta"]["id"]
    assert body["timeline"][0]["deltaId"]
    assert "claim" not in body
    assert body["sources"][0]["kind"] == "statuspage"
    facts = body["unknownFacts"]
    assert facts
    assert all(item["id"] and item["text"].strip() for item in facts)

    with database.connect() as connection:
        mapped = connection.execute(
            "SELECT claim_id FROM delta_claim_map WHERE delta_id = ?",
            (feed_item["delta"]["id"],),
        ).fetchone()
    assert mapped is not None
    claim_id = mapped["claim_id"]
    assert any(item["id"].startswith(f"{claim_id}:") for item in facts)

    knew = client.post(
        f"/v1/feed/items/{feed_item['id']}/feedback",
        headers=auth_headers,
        json={"type": "already_knew"},
    )
    assert knew.status_code == 200
    after_knew = client.get(f"/v1/events/{event_id}", headers=auth_headers).json()["unknownFacts"]
    assert all(not item["id"].startswith(f"{claim_id}:") for item in after_knew)


def test_follow_event(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    event_id, _ = _project_test_event(database)
    response = client.put(
        f"/v1/events/{event_id}/following",
        headers=auth_headers,
        json={"following": True},
    )
    assert response.status_code == 200
    assert response.json()["following"] is True
    detail = client.get(f"/v1/events/{event_id}", headers=auth_headers)
    assert detail.json()["following"] is True
    feed_item = next(
        item
        for item in client.get("/v1/feed", headers=auth_headers).json()["items"]
        if item["eventId"] == event_id
    )
    assert feed_item["following"] is True
