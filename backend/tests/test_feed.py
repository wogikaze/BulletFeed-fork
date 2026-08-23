from fastapi.testclient import TestClient

from app.database import Database
from app.db.seed import seed_catalog, seed_user_workspace

_IMPORTANCE_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_RELATION_RANK = {"direct": 3, "adjacent": 2, "reference": 1}


def _seed_demo_workspace(database: Database) -> None:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        seed_catalog(connection)
        seed_user_workspace(connection, user["id"])


def _feed_sort_key(item: dict) -> tuple[int, int, str, str]:
    return (
        _IMPORTANCE_RANK[item["importance"]["level"]],
        _RELATION_RANK[item["relation"]["level"]],
        item["updatedAt"],
        item["id"],
    )


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
    assert _feed_sort_key(first) >= _feed_sort_key(body["items"][1])

    page_two = client.get("/v1/feed", headers=auth_headers, params={"cursor": body["nextCursor"], "limit": 2})
    assert page_two.status_code == 200
    ids = {item["id"] for item in body["items"]}
    assert ids.isdisjoint({item["id"] for item in page_two.json()["items"]})


def test_feed_ranking_cursor_preserves_importance_relation_then_freshness(
    client: TestClient,
    auth_headers: dict[str, str],
    database: Database,
) -> None:
    _seed_demo_workspace(database)
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        rows = connection.execute(
            "SELECT id FROM feed_items WHERE user_id = ? ORDER BY id LIMIT 3",
            (user["id"],),
        ).fetchall()
        assert len(rows) == 3
        ids = [row["id"] for row in rows]
        connection.execute("UPDATE feed_items SET dismissed = 1 WHERE user_id = ?", (user["id"],))
        connection.execute(
            """
            UPDATE feed_items
            SET dismissed = 0, importance_level = 'high', relation_level = 'direct',
                updated_at = '2026-08-20T08:00:00Z'
            WHERE id = ?
            """,
            (ids[0],),
        )
        connection.execute(
            """
            UPDATE feed_items
            SET dismissed = 0, importance_level = 'high', relation_level = 'reference',
                updated_at = '2026-08-22T08:00:00Z'
            WHERE id = ?
            """,
            (ids[1],),
        )
        connection.execute(
            """
            UPDATE feed_items
            SET dismissed = 0, importance_level = 'low', relation_level = 'direct',
                updated_at = '2026-08-23T08:00:00Z'
            WHERE id = ?
            """,
            (ids[2],),
        )

    first_page = client.get("/v1/feed", headers=auth_headers, params={"limit": 2}).json()
    assert [item["id"] for item in first_page["items"]] == ids[:2]
    assert first_page["nextCursor"]

    second_page = client.get(
        "/v1/feed",
        headers=auth_headers,
        params={"limit": 2, "cursor": first_page["nextCursor"]},
    ).json()
    assert [item["id"] for item in second_page["items"]] == [ids[2]]


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
