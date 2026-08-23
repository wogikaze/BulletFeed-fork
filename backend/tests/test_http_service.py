import httpx
import pytest
from fastapi import HTTPException

from app.services.http import require_json


@pytest.mark.asyncio
async def test_require_json_marks_only_401_as_reauthorization() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_json(
            httpx.Response(401, json={"message": "Bad credentials"}),
            "GitHub API",
            reauthorization_on_auth_failure=True,
        )

    assert exc_info.value.status_code == 403
    assert "reauthorization" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_require_json_maps_primary_rate_limit_403_to_429() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_json(
            httpx.Response(
                403,
                headers={"x-ratelimit-remaining": "0"},
                json={"message": "API rate limit exceeded"},
            ),
            "GitHub API",
            reauthorization_on_auth_failure=True,
        )

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_require_json_maps_secondary_rate_limit_403_to_429() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_json(
            httpx.Response(403, json={"message": "You have exceeded a secondary rate limit."}),
            "GitHub API",
            reauthorization_on_auth_failure=True,
        )

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_require_json_does_not_mark_generic_403_as_reauthorization() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_json(
            httpx.Response(403, json={"message": "Resource not accessible by integration"}),
            "GitHub API",
            reauthorization_on_auth_failure=True,
        )

    assert exc_info.value.status_code == 502
    assert "reauthorization" not in str(exc_info.value.detail)
