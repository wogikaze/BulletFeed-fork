import time

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.config import Settings
from app.db.seed import seed_catalog, seed_user_workspace
from app.routers import auth as auth_router
from app.security import TokenCipher
from app.services import github

_REAL_LIST_REPOSITORIES = github.list_repositories


def _seed_demo_workspace(database) -> None:
    with database.connect() as connection:
        user = connection.execute("SELECT id FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
        assert user is not None
        seed_catalog(connection)
        seed_user_workspace(connection, user["id"])


def test_feed_contract_includes_traceable_sources(client, auth_headers, database) -> None:
    _seed_demo_workspace(database)

    response = client.get("/v1/feed", headers=auth_headers, params={"limit": 10})

    assert response.status_code == 200
    items = response.json()["items"]
    item = next(entry for entry in items if entry["eventId"] == "workers-runtime")
    assert item["sources"]
    source = item["sources"][0]
    assert source["publisher"]
    assert source["kind"]
    assert source["title"]
    assert source["url"].startswith("https://")
    assert source["evidence"]
    assert source["publishedAt"]
    assert source["retrievedAt"]


@pytest.mark.asyncio
async def test_github_callback_rotates_user_session_without_losing_user(
    client,
    database,
    monkeypatch,
) -> None:
    created = client.post("/v1/sessions").json()
    old_access_token = created["accessToken"]
    user_id = created["userId"]
    key = Fernet.generate_key().decode()
    cipher = TokenCipher(key)
    settings = Settings(
        github_client_id="client-id",
        github_client_secret="client-secret",
        token_encryption_key=key,
    )
    state = "bound-oauth-state-value-12345678901234567890"
    poll_token = "bound-poll-token-value"
    database.create_oauth_flow(
        flow_id="bound-flow",
        user_id=user_id,
        state=state,
        poll_token=poll_token,
        encrypted_verifier=cipher.encrypt("verifier"),
        expires_at=int(time.time()) + 600,
    )

    async def fake_exchange_code(_settings, _code, _verifier):
        return {"access_token": "github-token", "expires_in": 3600}

    async def fake_get_user(_settings, _token):
        return {"id": 4242, "login": "octocat", "avatar_url": None}

    monkeypatch.setattr(auth_router.github, "exchange_code", fake_exchange_code)
    monkeypatch.setattr(auth_router.github, "get_user", fake_get_user)

    response = await auth_router.github_callback(
        settings=settings,
        database=database,
        cipher=cipher,
        code="oauth-code",
        state_value=state,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "bulletfeed://oauth/github"
    status_result = database.get_oauth_status("bound-flow", poll_token, cipher)
    assert status_result is not None
    rotated_access_token = status_result["app_access_token"]
    assert rotated_access_token
    assert rotated_access_token != old_access_token
    assert client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {rotated_access_token}"},
    ).status_code == 200
    assert client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {old_access_token}"},
    ).status_code == 401


class _Response:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_expired_github_token_requires_reauthorization(monkeypatch) -> None:
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb

        async def get(self, url, *, headers, params):
            del url, headers, params
            return _Response(401, {"message": "Bad credentials"})

    monkeypatch.setattr(github, "list_repositories", _REAL_LIST_REPOSITORIES)
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: _Client())

    with pytest.raises(HTTPException) as exc_info:
        await github.list_repositories(Settings(), "expired-token")

    assert exc_info.value.status_code == 403
    assert "reauthorization" in str(exc_info.value.detail).lower()
