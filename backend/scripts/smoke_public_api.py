"""Manual smoke of public API v1 user-visible behavior."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Database
from app.dependencies import get_database
from app.main import app


def main() -> None:
    get_settings.cache_clear()
    db = Database(Path("data/smoke-api.db"))
    db.path.parent.mkdir(parents=True, exist_ok=True)
    if db.path.exists():
        db.path.unlink()
    db.initialize()
    app.dependency_overrides[get_database] = lambda: db
    client = TestClient(app)

    assert client.get("/v1/feed").status_code == 401
    session = client.post("/v1/sessions").json()
    headers = {"Authorization": f"Bearer {session['accessToken']}"}

    me = client.get("/v1/me", headers=headers).json()
    feed = client.get("/v1/feed", headers=headers).json()["items"]
    first = feed[0]
    second_get = client.get("/v1/feed", headers=headers).json()["items"]
    same_ids = {item["id"] for item in feed} == {item["id"] for item in second_get}

    detail = client.get(
        f"/v1/events/{first['eventId']}",
        headers=headers,
        params={"fromFeedItem": first["id"]},
    ).json()
    client.put(
        f"/v1/events/{first['eventId']}/following",
        headers=headers,
        json={"following": True},
    )
    client.put(f"/v1/feed/items/{first['id']}/read", headers=headers)
    unread = client.get("/v1/feed", headers=headers, params={"status": "unread"}).json()["items"]
    hidden = next(item for item in feed if item["eventId"] == "kotlin-release")
    client.post(
        f"/v1/feed/items/{hidden['id']}/feedback",
        headers=headers,
        json={"type": "not_relevant"},
    )
    after_hide = {item["id"] for item in client.get("/v1/feed", headers=headers).json()["items"]}
    exposures = client.post(
        "/v1/feed/exposures",
        headers=headers,
        json={"items": [{"deliveryId": first["deliveryId"], "displayedAt": "2026-08-18T05:00:00Z"}]},
    ).json()
    ignored = client.post(
        "/v1/feed/exposures",
        headers=headers,
        json={"items": [{"deliveryId": "dlv_unknown", "displayedAt": "2026-08-18T05:00:00Z"}]},
    ).json()

    print("session", session["userId"])
    print("me.onboardingCompleted", me["onboardingCompleted"])
    print("feed.count", len(feed))
    print("feed.hasDelta", bool(first["delta"]["id"]))
    print("feed.leaksObservation", "observation" in first)
    print("getFeedDoesNotConsumeItems", same_ids)
    print("openedDelta", detail.get("openedDelta", {}).get("id"))
    print("currentState.phase", detail["currentState"]["phase"])
    print("unreadOmitsRead", first["id"] not in {item["id"] for item in unread})
    print("notRelevantHidesOnlyThatItem", hidden["id"] not in after_hide)
    print("exposureAccepted", exposures["accepted"])
    print("unknownDeliveryIgnored", ignored["accepted"] == 0)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


if __name__ == "__main__":
    main()
