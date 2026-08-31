from fastapi.testclient import TestClient

from app.database import Database
from app.db.seed import seed_catalog, seed_user_workspace


def _seed_demo_workspace(database: Database) -> None:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        seed_catalog(connection)
        seed_user_workspace(connection, user["id"])


def test_feed_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/feed")
    assert response.status_code == 401


def test_feed_does_not_implicitly_create_demo_items(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get("/v1/feed", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_feed_returns_public_items_and_cursor(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_workspace(database)
    response = client.get("/v1/feed", headers=auth_headers, params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["nextCursor"]
    first = body["items"][0]
    assert first["id"].startswith("fi_")
    assert first["delta"]["id"]
    assert first["deliveryId"]
    assert "observation" not in first
    reason = first["displayReason"]
    assert reason["policyVersion"]
    assert reason["rankingPolicyVersion"]
    assert reason["primaryCode"]
    assert reason["text"]
    assert reason["codes"]
    assert reason["matchKind"]
    assert reason["deltaKind"]

    page_two = client.get("/v1/feed", headers=auth_headers, params={"cursor": body["nextCursor"], "limit": 2})
    assert page_two.status_code == 200
    ids = {item["id"] for item in body["items"]}
    assert ids.isdisjoint({item["id"] for item in page_two.json()["items"]})


def test_feed_ranking_cursor_is_stable_for_one_ranking_version(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_workspace(database)
    first_page = client.get("/v1/feed", headers=auth_headers, params={"limit": 2}).json()
    assert len(first_page["items"]) == 2
    assert first_page["nextCursor"]
    first_ids = [item["id"] for item in first_page["items"]]

    replay = client.get("/v1/feed", headers=auth_headers, params={"limit": 2}).json()
    assert [item["id"] for item in replay["items"]] == first_ids
    assert replay["nextCursor"] == first_page["nextCursor"]

    second_page = client.get(
        "/v1/feed",
        headers=auth_headers,
        params={"limit": 2, "cursor": first_page["nextCursor"]},
    ).json()
    second_ids = [item["id"] for item in second_page["items"]]
    assert second_ids
    assert set(first_ids).isdisjoint(second_ids)

    stale = client.get(
        "/v1/feed",
        headers=auth_headers,
        params={"limit": 2, "cursor": "not-a-valid-cursor"},
    )
    assert stale.status_code == 422
    assert stale.json()["error"]["code"] == "validation_error"


def test_feed_rejects_invalid_limit(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/v1/feed", headers=auth_headers, params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_mark_read_and_feedback_and_exposures(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_workspace(database)
    feed = client.get("/v1/feed", headers=auth_headers).json()["items"]
    target = next(item for item in feed if item["eventId"] == "workers-runtime")

    read = client.put(f"/v1/feed/items/{target['id']}/read", headers=auth_headers)
    assert read.status_code == 200
    assert read.json()["status"] == "read"

    important = client.post(
        f"/v1/feed/items/{target['id']}/feedback",
        headers=auth_headers,
        json={"type": "important"},
    )
    assert important.status_code == 200
    assert important.json()["type"] == "important"

    missing = client.put("/v1/feed/items/missing/read", headers=auth_headers)
    assert missing.status_code == 404

    dismissed = next(item for item in feed if item["eventId"] == "kotlin-release")
    hide = client.post(
        f"/v1/feed/items/{dismissed['id']}/feedback",
        headers=auth_headers,
        json={"type": "not_relevant"},
    )
    assert hide.status_code == 200
    remaining = client.get("/v1/feed", headers=auth_headers).json()["items"]
    assert dismissed["id"] not in {item["id"] for item in remaining}

    exposures = client.post(
        "/v1/feed/exposures",
        headers=auth_headers,
        json={
            "items": [
                {
                    "deliveryId": target["deliveryId"],
                    "displayedAt": "2026-08-18T05:00:00Z",
                    "dwellMs": 1200,
                    "visibleRatio": 0.8,
                }
            ]
        },
    )
    assert exposures.status_code == 200
    assert exposures.json()["accepted"] == 1

    ignored = client.post(
        "/v1/feed/exposures",
        headers=auth_headers,
        json={"items": [{"deliveryId": "dlv_unknown", "displayedAt": "2026-08-18T05:00:00Z"}]},
    )
    assert ignored.status_code == 200
    assert ignored.json()["accepted"] == 0

    remaining_feed = client.get("/v1/feed", headers=auth_headers).json()["items"]
    brief = remaining_feed[0]
    rejected = client.post(
        "/v1/feed/exposures",
        headers=auth_headers,
        json={
            "items": [
                {
                    "deliveryId": brief["deliveryId"],
                    "displayedAt": "2026-08-18T05:01:00Z",
                    "dwellMs": 80,
                    "visibleRatio": 0.1,
                }
            ]
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["accepted"] == 0

    accepted_metrics = client.post(
        "/v1/feed/exposures",
        headers=auth_headers,
        json={
            "items": [
                {
                    "deliveryId": brief["deliveryId"],
                    "displayedAt": "2026-08-18T05:02:00Z",
                    "dwellMs": 1200,
                    "visibleRatio": 0.8,
                }
            ]
        },
    )
    assert accepted_metrics.status_code == 200
    assert accepted_metrics.json()["accepted"] == 1
