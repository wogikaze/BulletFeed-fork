import re
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.services.http import require_json

PAGE_ID_PATTERN = re.compile(r"^[a-z0-9]{8,32}$")


async def get_summary(settings: Settings, page_id: str) -> dict[str, Any]:
    if not PAGE_ID_PATTERN.fullmatch(page_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid Statuspage ID")
    url = f"https://{page_id}.statuspage.io/api/v2/summary.json"
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.get(url, headers={"User-Agent": "BulletFeed-local-prototype/0.1"})
    data = await require_json(response, "Statuspage")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Statuspage returned invalid data"
        )
    return data
