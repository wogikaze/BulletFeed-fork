from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.services.http import require_json


async def query_vulnerabilities(
    settings: Settings,
    *,
    ecosystem: str,
    package: str,
    version: str,
) -> list[dict[str, Any]]:
    payload = {"package": {"ecosystem": ecosystem, "name": package}, "version": version}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.post("https://api.osv.dev/v1/query", json=payload)
    data = await require_json(response, "OSV")
    if not isinstance(data, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OSV returned invalid data")
    vulnerabilities = data.get("vulns", [])
    if not isinstance(vulnerabilities, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="OSV returned invalid vulnerabilities"
        )
    return vulnerabilities
