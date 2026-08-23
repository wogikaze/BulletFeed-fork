from __future__ import annotations

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.services.http import require_json
from app.services.sbom_packages import OsvPackage


async def query_osv_batch(
    settings: Settings,
    packages: tuple[OsvPackage, ...],
) -> tuple[tuple[dict, ...], ...]:
    if not packages:
        return ()
    payload = {
        "queries": [
            {
                "package": {"ecosystem": package.ecosystem, "name": package.name},
                "version": package.version,
            }
            for package in packages
        ]
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        response = await client.post("https://api.osv.dev/v1/querybatch", json=payload)
    data = await require_json(response, "OSV querybatch")
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OSV querybatch returned invalid data",
        )
    results = data["results"]
    if len(results) != len(packages):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OSV querybatch result count mismatch",
        )

    normalized: list[tuple[dict, ...]] = []
    for result in results:
        if not isinstance(result, dict):
            normalized.append(())
            continue
        vulnerabilities = result.get("vulns", [])
        if not isinstance(vulnerabilities, list):
            normalized.append(())
            continue
        normalized.append(tuple(item for item in vulnerabilities if isinstance(item, dict)))
    return tuple(normalized)
