from __future__ import annotations

from typing import Any

from app.config import Settings
from app.database import Database
from app.services.osv import query_vulnerabilities
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline


def normalize_osv_vulnerabilities(
    *,
    ecosystem: str,
    package: str,
    version: str,
    vulnerabilities: list[dict[str, Any]],
) -> tuple[NormalizedObservation, ...]:
    source_key = f"{ecosystem}:{package}@{version}"
    items: list[NormalizedObservation] = []
    for vulnerability in vulnerabilities:
        vulnerability_id = vulnerability.get("id")
        if not isinstance(vulnerability_id, str) or not vulnerability_id:
            continue
        published_at = vulnerability.get("published") or vulnerability.get("modified")
        items.append(
            NormalizedObservation(
                source_type="osv",
                source_key=source_key,
                source_observation_id=vulnerability_id,
                payload=vulnerability,
                original_url=f"https://osv.dev/vulnerability/{vulnerability_id}",
                published_at=published_at if isinstance(published_at, str) else None,
            )
        )
    return tuple(items)


async def crawl_osv(
    settings: Settings,
    database: Database,
    *,
    ecosystem: str,
    package: str,
    version: str,
    retrieved_at: str,
):
    vulnerabilities = await query_vulnerabilities(
        settings,
        ecosystem=ecosystem,
        package=package,
        version=version,
    )
    observations = normalize_osv_vulnerabilities(
        ecosystem=ecosystem,
        package=package,
        version=version,
        vulnerabilities=vulnerabilities,
    )
    return SourceIngestionPipeline(database).ingest_many(observations, retrieved_at=retrieved_at)
