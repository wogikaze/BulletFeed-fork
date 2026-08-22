from fastapi.testclient import TestClient


def test_event_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/events/workers-runtime")
    assert response.status_code == 401


def test_event_detail_and_opened_delta(client: TestClient, auth_headers: dict[str, str]) -> None:
    missing = client.get("/v1/events/missing", headers=auth_headers)
    assert missing.status_code == 404

    feed_item = next(
        item
        for item in client.get("/v1/feed", headers=auth_headers).json()["items"]
        if item["eventId"] == "workers-runtime"
    )
    detail = client.get(
        "/v1/events/workers-runtime",
        headers=auth_headers,
        params={"fromFeedItem": feed_item["id"]},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["currentState"]["phase"] == "identified"
    assert body["latestDelta"]["id"] == "delta_workers_identified"
    assert body["openedDelta"]["id"] == feed_item["delta"]["id"]
    assert body["timeline"][0]["deltaId"]
    assert "claim" not in body
    assert body["sources"][0]["kind"] in {
        "statuspage",
        "github_advisory",
        "osv",
        "github_release",
        "official_changelog",
        "documentation",
    }


def test_follow_event(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.put(
        "/v1/events/workers-runtime/following",
        headers=auth_headers,
        json={"following": True},
    )
    assert response.status_code == 200
    assert response.json()["following"] is True
    detail = client.get("/v1/events/workers-runtime", headers=auth_headers)
    assert detail.json()["following"] is True
    feed_item = next(
        item
        for item in client.get("/v1/feed", headers=auth_headers).json()["items"]
        if item["eventId"] == "workers-runtime"
    )
    assert feed_item["following"] is True
