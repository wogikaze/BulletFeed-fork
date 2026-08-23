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
        "User-Agent": "BulletFeed/0.1",
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
    data = await require_json(
        response,
        "GitHub API",
        reauthorization_on_auth_failure=True,
    )
    if not isinstance(data, dict) or not isinstance(data.get("id"), int) or not data.get("login"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub returned an invalid user")
    return data


async def list_repositories(settings: Settings, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        for page in range(1, 11):
            params = {
                "per_page": 100,
                "page": page,
                "sort": "pushed",
                "direction": "desc",
                "affiliation": "owner,collaborator,organization_member",
            }
            response = await client.get(f"{API_URL}/user/repos", headers=_headers(token), params=params)
            data = await require_json(
                response,
                "GitHub API",
                reauthorization_on_auth_failure=True,
            )
            if not isinstance(data, list):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="GitHub returned invalid repositories",
                )
            items.extend(item for item in data if isinstance(item, dict))
            if len(data) < 100:
                break
    return items


async def repository_accessible(
    settings: Settings,
    owner: str,
    repository: str,
    token: str,
) -> dict[str, Any] | None:
    """Return repository metadata when this user's token can still read it."""
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(
            f"{API_URL}/repos/{owner}/{repository}",
            headers=_headers(token),
        )
    if response.status_code == 404:
        return None
    data = await require_json(
        response,
        "GitHub repository access",
        reauthorization_on_auth_failure=True,
    )
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned invalid repository metadata",
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
    data = await require_json(
        response,
        "GitHub API",
        reauthorization_on_auth_failure=token is not None,
    )
    if not isinstance(data, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub returned invalid releases"
        )
    return data


async def list_global_advisories(
    settings: Settings,
    *,
    ecosystem: str | None = None,
    token: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, str | int] = {"per_page": 100, "sort": "updated", "direction": "desc"}
    if ecosystem:
        params["ecosystem"] = ecosystem
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(
            f"{API_URL}/advisories",
            headers=_headers(token),
            params=params,
        )
    data = await require_json(
        response,
        "GitHub Advisory API",
        reauthorization_on_auth_failure=token is not None,
    )
    if not isinstance(data, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned invalid global advisories",
        )
    return [item for item in data if isinstance(item, dict)]


async def get_repository_languages(
    settings: Settings,
    owner: str,
    repository: str,
    token: str | None = None,
) -> dict[str, int]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(
            f"{API_URL}/repos/{owner}/{repository}/languages",
            headers=_headers(token),
        )
    data = await require_json(
        response,
        "GitHub API",
        reauthorization_on_auth_failure=token is not None,
    )
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub returned invalid languages"
        )
    return {str(k): int(v) for k, v in data.items() if isinstance(v, (int, float))}


async def get_repository_topics(
    settings: Settings,
    owner: str,
    repository: str,
    token: str | None = None,
) -> list[str]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(
            f"{API_URL}/repos/{owner}/{repository}/topics",
            headers=_headers(token),
        )
    data = await require_json(
        response,
        "GitHub API",
        reauthorization_on_auth_failure=token is not None,
    )
    if not isinstance(data, dict) or not isinstance(data.get("names"), list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub returned invalid topics"
        )
    return [str(name) for name in data["names"] if isinstance(name, str)]
