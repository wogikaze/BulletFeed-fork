from fastapi.testclient import TestClient


def test_feed_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/feed")
    assert response.status_code == 401


def test_feed_returns_public_items_and_cursor(client: TestClient, auth_headers: dict[str, str]) -> None:
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
    assert first["updatedAt"] >= body["items"][1]["updatedAt"]

    page_two = client.get("/v1/feed", headers=auth_headers, params={"cursor": body["nextCursor"], "limit": 2})
    assert page_two.status_code == 200
    ids = {item["id"] for item in body["items"]}
    assert ids.isdisjoint({item["id"] for item in page_two.json()["items"]})


def test_feed_rejects_invalid_limit(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/v1/feed", headers=auth_headers, params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_mark_read_and_feedback_and_exposures(client: TestClient, auth_headers: dict[str, str]) -> None:
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
        json={"items": [{"deliveryId": target["deliveryId"], "displayedAt": "2026-08-18T05:00:00Z"}]},
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
