from typing import Any

import httpx
from fastapi import HTTPException, status


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return True
    if response.status_code != status.HTTP_403_FORBIDDEN:
        return False
    if response.headers.get("x-ratelimit-remaining") == "0" or response.headers.get("retry-after"):
        return True
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    message = str(payload.get("message") or "").casefold()
    return "rate limit" in message


async def require_json(
    response: httpx.Response,
    source_name: str,
    *,
    reauthorization_on_auth_failure: bool = False,
) -> Any:
    if reauthorization_on_auth_failure and response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{source_name} credentials require reauthorization",
        )
    if _is_rate_limited(response):
        retry_after = response.headers.get("retry-after")
        detail = f"{source_name} rate limit exceeded"
        if retry_after:
            detail += f"; retry after {retry_after} seconds"
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)
    if response.status_code >= 400:
        retry_after = response.headers.get("retry-after")
        detail = f"{source_name} returned HTTP {response.status_code}"
        if retry_after:
            detail += f"; retry after {retry_after} seconds"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{source_name} returned invalid JSON",
        ) from exc
