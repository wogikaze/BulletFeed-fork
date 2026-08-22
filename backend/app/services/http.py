from typing import Any

import httpx
from fastapi import HTTPException, status


async def require_json(response: httpx.Response, source_name: str) -> Any:
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
