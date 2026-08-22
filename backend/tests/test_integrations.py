from fastapi.testclient import TestClient


def test_github_repositories_and_disconnect(client: TestClient, auth_headers: dict[str, str]) -> None:
    listed = client.get("/v1/me/integrations/github/repositories", headers=auth_headers, params={"limit": 2})
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["items"]) == 2
    assert "connected" not in body
    first_id = body["items"][0]["id"]

    updated = client.put(
        "/v1/me/integrations/github/repositories",
        headers=auth_headers,
        json={"repositoryIds": [first_id]},
    )
    assert updated.status_code == 200
    assert updated.json()["connected"] is True

    connection = client.get("/v1/me/integrations/github", headers=auth_headers)
    assert connection.status_code == 200
    assert "repositories" not in connection.json()

    removed = client.delete("/v1/me/integrations/github", headers=auth_headers)
    assert removed.status_code == 204
    assert client.get("/v1/me/integrations/github", headers=auth_headers).json()["connected"] is False


def test_github_authorize_requires_config(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/v1/me/integrations/github/authorize", headers=auth_headers)
    assert response.status_code == 503
    assert "error" in response.json()


def test_security_alerts_and_notifications(client: TestClient, auth_headers: dict[str, str]) -> None:
    alerts = client.get("/v1/me/security/alerts", headers=auth_headers)
    assert alerts.status_code == 200
    assert any(item["id"] == "vuln-next-auth" for item in alerts.json()["items"])

    patched = client.patch(
        "/v1/me/security/alerts/vuln-next-auth",
        headers=auth_headers,
        json={"status": "in_progress"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"
    assert client.get("/v1/me/security/alerts/missing", headers=auth_headers).status_code == 404

    unread = client.get("/v1/me/notifications", headers=auth_headers, params={"status": "unread"})
    assert unread.status_code == 200
    assert all(item["read"] is False for item in unread.json()["items"])

    marked = client.patch(
        "/v1/me/notifications/notification-next-auth",
        headers=auth_headers,
        json={"read": True},
    )
    assert marked.json()["read"] is True
    result = client.post("/v1/me/notifications/read-all", headers=auth_headers)
    assert result.json()["updatedCount"] >= 1
