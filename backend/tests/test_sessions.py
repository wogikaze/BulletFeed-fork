from fastapi.testclient import TestClient


def test_create_session_returns_bearer_token(client: TestClient) -> None:
    response = client.post("/v1/sessions")
    assert response.status_code == 200
    body = response.json()
    assert body["accessToken"]
    assert body["userId"].startswith("usr_")


def test_protected_route_requires_bearer(client: TestClient) -> None:
    response = client.get("/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
