from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.services.http import require_json

API_URL = "https://api.github.com"
OAUTH_EXCHANGE_URL = "https://github.com/login/oauth/access_token"


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "BulletFeed-local-prototype/0.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def exchange_code(settings: Settings, code: str, verifier: str) -> dict[str, Any]:
    payload = {
        "client_id": settings.github_client_id,
        "client_secret": settings.github_client_secret.get_secret_value(),
        "code": code,
        "redirect_uri": settings.github_callback_url,
        "code_verifier": verifier,
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.post(OAUTH_EXCHANGE_URL, headers={"Accept": "application/json"}, data=payload)
    data = await require_json(response, "GitHub OAuth")
    if not isinstance(data, dict) or not data.get("access_token"):
        error = data.get("error_description") if isinstance(data, dict) else None
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=error or "GitHub OAuth did not return an access token",
        )
    return data


async def get_user(settings: Settings, token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(f"{API_URL}/user", headers=_headers(token))
    data = await require_json(response, "GitHub API")
    if not isinstance(data, dict) or not isinstance(data.get("id"), int) or not data.get("login"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub returned an invalid user")
    return data


async def list_repositories(settings: Settings, token: str) -> list[dict[str, Any]]:
    params = {"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator,organization_member"}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(f"{API_URL}/user/repos", headers=_headers(token), params=params)
    data = await require_json(response, "GitHub API")
    if not isinstance(data, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub returned invalid repositories"
        )
    return data


async def list_releases(
    settings: Settings,
    owner: str,
    repository: str,
    token: str | None = None,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(
            f"{API_URL}/repos/{owner}/{repository}/releases",
            headers=_headers(token),
            params={"per_page": 20},
        )
    data = await require_json(response, "GitHub API")
    if not isinstance(data, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub returned invalid releases"
        )
    return data
