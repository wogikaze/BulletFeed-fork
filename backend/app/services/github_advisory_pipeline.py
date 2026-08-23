from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.database import Database
from app.services.github import list_global_advisories
from app.services.github_advisory_source import normalize_github_advisories
from app.services.ledger_projection import LedgerProjector
from app.services.source_dependence import canonical_github_advisory_id
from app.services.source_ingestion import SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore
from app.stores.github_advisory_alias_store import GitHubAdvisoryAliasStore


@dataclass(frozen=True)
class GitHubAdvisoryIngestResult:
    event_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]


def _canonical_event_key(ghsa_id: str) -> str:
    return f"github-advisory:{ghsa_id.upper()}"


def ingest_github_advisory_events(
    database: Database,
    *,
    advisories: list[dict[str, Any]],
    retrieved_at: str,
    ecosystem: str | None = None,
) -> GitHubAdvisoryIngestResult:
    observations = SourceIngestionPipeline(database).ingest_many(
        normalize_github_advisories(advisories, ecosystem=ecosystem),
        retrieved_at=retrieved_at,
    )
    ledger = ClaimLedgerStore(database)
    aliases = GitHubAdvisoryAliasStore(database, ledger)
    projector = LedgerProjector(database)
    event_ids: list[str] = []
    claim_ids: list[str] = []

    canonical_observations = []
    duplicate_observations = []
    for observation in observations:
        direct_ghsa_id = str(observation.payload["ghsa_id"]).upper()
        canonical_ghsa_id = canonical_github_advisory_id(observation.payload) or direct_ghsa_id
        if canonical_ghsa_id != direct_ghsa_id:
            duplicate_observations.append((observation, direct_ghsa_id, canonical_ghsa_id))
        else:
            canonical_observations.append(observation)

    for observation in canonical_observations:
        payload = observation.payload
        ghsa_id = str(payload["ghsa_id"]).upper()
        summary = payload.get("summary") if isinstance(payload.get("summary"), str) else ""
        severity = payload.get("severity") if isinstance(payload.get("severity"), str) else "unknown"
        withdrawn_at = _timestamp(payload.get("withdrawn_at"))
        state = "withdrawn" if withdrawn_at else "active"
        valid_at = (
            withdrawn_at
            or _timestamp(payload.get("published_at"))
            or observation.published_at
            or retrieved_at
        )
        source_updated_at = _timestamp(payload.get("updated_at")) or valid_at
        detail = f"[{severity}] {summary.strip()}" if summary.strip() else f"{ghsa_id} is {state}."
        claim = ledger.ingest(
            observation,
            source_event_id=ghsa_id,
            canonical_event_key=_canonical_event_key(ghsa_id),
            title=f"{ghsa_id} — {summary.strip() or 'GitHub Security Advisory'}",
            slot="advisory_state",
            value=state,
            detail=detail,
            valid_at=valid_at,
            source_updated_at=source_updated_at,
            evidence_text=detail,
        )
        aliases.attach_pending(canonical_ghsa_id=ghsa_id, claim_id=claim.claim_id)
        projector.project_event(claim.event_id)
        event_ids.append(claim.event_id)
        claim_ids.append(claim.claim_id)

    for observation, alias_ghsa_id, canonical_ghsa_id in duplicate_observations:
        attached = aliases.record(
            observation,
            alias_ghsa_id=alias_ghsa_id,
            canonical_ghsa_id=canonical_ghsa_id,
        )
        if attached is not None:
            _, event_id = attached
            projector.project_event(event_id)
            event_ids.append(event_id)

    return GitHubAdvisoryIngestResult(
        event_ids=tuple(dict.fromkeys(event_ids)),
        claim_ids=tuple(claim_ids),
    )


async def crawl_github_advisory_events(
    settings: Settings,
    database: Database,
    *,
    retrieved_at: str,
    ecosystem: str | None = None,
    token: str | None = None,
) -> GitHubAdvisoryIngestResult:
    advisories = await list_global_advisories(settings, ecosystem=ecosystem, token=token)
    return ingest_github_advisory_events(
        database,
        advisories=advisories,
        retrieved_at=retrieved_at,
        ecosystem=ecosystem,
    )


def _timestamp(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
