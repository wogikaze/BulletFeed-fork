from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.database import Database
from app.services.ledger_projection import LedgerProjector
from app.services.osv import query_vulnerabilities
from app.services.osv_source import normalize_osv_vulnerabilities
from app.services.source_ingestion import SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


@dataclass(frozen=True)
class OsvIngestResult:
    event_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]


def ingest_osv_events(
    database: Database,
    *,
    ecosystem: str,
    package: str,
    version: str,
    vulnerabilities: list[dict[str, Any]],
    retrieved_at: str,
) -> OsvIngestResult:
    normalized = normalize_osv_vulnerabilities(
        ecosystem=ecosystem,
        package=package,
        version=version,
        vulnerabilities=vulnerabilities,
    )
    observations = SourceIngestionPipeline(database).ingest_many(
        normalized,
        retrieved_at=retrieved_at,
    )
    ledger = ClaimLedgerStore(database)
    projector = LedgerProjector(database)
    event_ids: list[str] = []
    claim_ids: list[str] = []

    for observation in observations:
        payload = observation.payload
        vulnerability_id = str(payload["id"])
        summary = payload.get("summary") if isinstance(payload.get("summary"), str) else ""
        details = payload.get("details") if isinstance(payload.get("details"), str) else ""
        detail = summary.strip() or details.strip() or f"{vulnerability_id} affects {package} {version}."
        valid_at = (
            _timestamp(payload.get("published"))
            or _timestamp(payload.get("modified"))
            or observation.published_at
            or retrieved_at
        )
        source_updated_at = _timestamp(payload.get("modified")) or valid_at
        claim = ledger.ingest(
            observation,
            source_event_id=vulnerability_id,
            title=f"{package} {version} — {vulnerability_id}",
            slot="vulnerability_advisory",
            value="affected",
            detail=detail,
            valid_at=valid_at,
            source_updated_at=source_updated_at,
            evidence_text=detail,
        )
        projector.project_event(claim.event_id)
        event_ids.append(claim.event_id)
        claim_ids.append(claim.claim_id)

    return OsvIngestResult(
        event_ids=tuple(dict.fromkeys(event_ids)),
        claim_ids=tuple(claim_ids),
    )


async def crawl_osv_events(
    settings: Settings,
    database: Database,
    *,
    ecosystem: str,
    package: str,
    version: str,
    retrieved_at: str,
) -> OsvIngestResult:
    vulnerabilities = await query_vulnerabilities(
        settings,
        ecosystem=ecosystem,
        package=package,
        version=version,
    )
    return ingest_osv_events(
        database,
        ecosystem=ecosystem,
        package=package,
        version=version,
        vulnerabilities=vulnerabilities,
        retrieved_at=retrieved_at,
    )


def _timestamp(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
