from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.database import Database
from app.services.event_access import project_repository_event_access
from app.services.feed_projection import project_event_for_audience
from app.services.github_sbom_source import fetch_github_sbom, normalize_github_sbom
from app.services.ledger_projection import LedgerProjector
from app.services.osv_batch import query_osv_batch
from app.services.sbom_packages import OsvPackage, extract_osv_packages
from app.services.security_projection import SecurityProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


@dataclass(frozen=True)
class DependencySecurityIngestResult:
    event_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    package_count: int


def _event_key(repository_key: str, package: OsvPackage, vulnerability_id: str) -> str:
    return "|".join(
        (
            "dependency-security",
            repository_key.casefold(),
            package.ecosystem.casefold(),
            package.name.casefold(),
            vulnerability_id.upper(),
        )
    )


def _query_observation(
    repository_key: str,
    package: OsvPackage,
    vulnerabilities: tuple[dict, ...],
) -> NormalizedObservation:
    return NormalizedObservation(
        source_type="osv",
        source_key=repository_key,
        source_observation_id=f"query|{package.purl}",
        payload={
            "query": {
                "ecosystem": package.ecosystem,
                "name": package.name,
                "version": package.version,
                "purl": package.purl,
            },
            "vulnerability_ids": [
                item["id"]
                for item in vulnerabilities
                if isinstance(item.get("id"), str) and item["id"]
            ],
            "repository": repository_key,
        },
        original_url="https://api.osv.dev/v1/querybatch",
        published_at=None,
    )


def ingest_sbom_security_events(
    database: Database,
    *,
    owner: str,
    repository: str,
    sbom_response: dict[str, Any],
    batch_results: tuple[tuple[dict, ...], ...],
    retrieved_at: str,
) -> DependencySecurityIngestResult:
    packages = extract_osv_packages(sbom_response)
    if len(packages) != len(batch_results):
        raise ValueError("OSV batch results must align with extracted SBOM packages")

    ingestion = SourceIngestionPipeline(database)
    sbom_observation = ingestion.ingest_many(
        (normalize_github_sbom(owner, repository, sbom_response),),
        retrieved_at=retrieved_at,
    )[0]
    ledger = ClaimLedgerStore(database)
    projector = LedgerProjector(database)
    repository_key = f"{owner}/{repository}"
    prior_affected = _active_affected_events(database, repository_key=repository_key)
    current_packages = {(package.ecosystem, package.name): package for package in packages}
    query_observations: dict[tuple[str, str], Any] = {}
    current_affected_event_ids: set[str] = set()
    event_ids: list[str] = []
    claim_ids: list[str] = []

    for package, vulnerabilities in zip(packages, batch_results, strict=True):
        query_observation = ingestion.ingest_many(
            (_query_observation(repository_key, package, vulnerabilities),),
            retrieved_at=retrieved_at,
        )[0]
        query_observations[(package.ecosystem, package.name)] = query_observation
        for vulnerability in vulnerabilities:
            vulnerability_id = vulnerability.get("id")
            if not isinstance(vulnerability_id, str) or not vulnerability_id:
                continue
            published_at = _timestamp(vulnerability.get("published")) or _timestamp(
                vulnerability.get("modified")
            )
            normalized = NormalizedObservation(
                source_type="osv",
                source_key=repository_key,
                source_observation_id=f"{vulnerability_id}|{package.purl}",
                payload={
                    "vulnerability": vulnerability,
                    "dependency": {
                        "ecosystem": package.ecosystem,
                        "name": package.name,
                        "version": package.version,
                        "purl": package.purl,
                    },
                    "repository": repository_key,
                },
                original_url=f"https://osv.dev/vulnerability/{vulnerability_id}",
                published_at=published_at,
            )
            osv_observation = ingestion.ingest_many(
                (normalized,),
                retrieved_at=retrieved_at,
            )[0]
            summary = (
                vulnerability.get("summary")
                if isinstance(vulnerability.get("summary"), str)
                else ""
            )
            details = (
                vulnerability.get("details")
                if isinstance(vulnerability.get("details"), str)
                else ""
            )
            detail = summary.strip() or details.strip() or (
                f"{package.name} {package.version} is affected by {vulnerability_id}."
            )
            valid_at = published_at or retrieved_at
            source_updated_at = _timestamp(vulnerability.get("modified")) or valid_at
            claim = ledger.ingest(
                osv_observation,
                source_event_id=vulnerability_id,
                canonical_event_key=_event_key(repository_key, package, vulnerability_id),
                title=(
                    f"{repository_key} — {package.name} — {vulnerability_id}"
                ),
                slot="dependency_vulnerability",
                value="affected",
                detail=detail,
                valid_at=valid_at,
                source_updated_at=source_updated_at,
                evidence_text=f"{vulnerability_id}: {detail}",
            )
            ledger.add_evidence(
                claim.claim_id,
                sbom_observation,
                evidence_text=(
                    f"{repository_key} SBOM contains {package.name} {package.version} "
                    f"({package.purl})."
                ),
            )
            projector.project_event(claim.event_id)
            _project_for_watchers(
                database,
                repository_key=repository_key,
                event_id=claim.event_id,
            )
            current_affected_event_ids.add(claim.event_id)
            event_ids.append(claim.event_id)
            claim_ids.append(claim.claim_id)

    for prior_event_id, metadata in prior_affected.items():
        if prior_event_id in current_affected_event_ids:
            continue
        package_identity = (metadata["ecosystem"], metadata["name"])
        current_package = current_packages.get(package_identity)
        query_observation = query_observations.get(package_identity)
        primary_observation = query_observation or sbom_observation
        vulnerability_id = metadata["vulnerability_id"]
        if current_package is None:
            detail = (
                f"{metadata['name']} is no longer present in the current {repository_key} SBOM; "
                f"{vulnerability_id} is no longer an active dependency finding."
            )
            title_version = metadata["version"]
        else:
            detail = (
                f"{metadata['name']} {current_package.version} is no longer reported affected by "
                f"{vulnerability_id} for the current {repository_key} SBOM."
            )
            title_version = current_package.version
        package_for_identity = current_package or OsvPackage(
            ecosystem=metadata["ecosystem"],
            name=metadata["name"],
            version=metadata["version"],
            purl=metadata["purl"],
        )
        claim = ledger.ingest(
            primary_observation,
            source_event_id=vulnerability_id,
            canonical_event_key=_event_key(repository_key, package_for_identity, vulnerability_id),
            title=f"{repository_key} — {metadata['name']} — {vulnerability_id}",
            slot="dependency_vulnerability",
            value="fixed",
            detail=detail,
            valid_at=retrieved_at,
            source_updated_at=retrieved_at,
            evidence_text=detail,
        )
        if primary_observation.id != sbom_observation.id:
            ledger.add_evidence(
                claim.claim_id,
                sbom_observation,
                evidence_text=f"Current {repository_key} SBOM was used to reconcile {vulnerability_id}.",
            )
        projector.project_event(claim.event_id)
        _project_for_watchers(
            database,
            repository_key=repository_key,
            event_id=claim.event_id,
        )
        event_ids.append(claim.event_id)
        claim_ids.append(claim.claim_id)
        del title_version  # retained in detail via current package when available

    return DependencySecurityIngestResult(
        event_ids=tuple(dict.fromkeys(event_ids)),
        claim_ids=tuple(claim_ids),
        package_count=len(packages),
    )


def _active_affected_events(
    database: Database,
    *,
    repository_key: str,
) -> dict[str, dict[str, str]]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT c.event_id, c.value_text, r.relation_type, o.payload_json
            FROM state_claims c
            JOIN claim_relations r ON r.new_claim_id = c.id
            JOIN observations o ON o.id = c.observation_id
            JOIN ledger_events e ON e.id = c.event_id
            WHERE e.source_key = ? AND c.slot = 'dependency_vulnerability'
            ORDER BY c.valid_at, c.source_updated_at, c.id
            """,
            (repository_key,),
        ).fetchall()
    latest: dict[str, Any] = {}
    metadata: dict[str, dict[str, str]] = {}
    for row in rows:
        if row["relation_type"] != "UNRESOLVED_CONTRADICTION":
            latest[row["event_id"]] = row
        payload = json.loads(row["payload_json"])
        vulnerability = payload.get("vulnerability")
        dependency = payload.get("dependency")
        if not isinstance(vulnerability, dict) or not isinstance(dependency, dict):
            continue
        vulnerability_id = vulnerability.get("id")
        required = {
            "ecosystem": dependency.get("ecosystem"),
            "name": dependency.get("name"),
            "version": dependency.get("version"),
            "purl": dependency.get("purl"),
            "vulnerability_id": vulnerability_id,
        }
        if all(isinstance(value, str) and value for value in required.values()):
            metadata[row["event_id"]] = required  # type: ignore[assignment]
    return {
        event_id: metadata[event_id]
        for event_id, row in latest.items()
        if row["value_text"] == "affected" and event_id in metadata
    }


def _project_for_watchers(database: Database, *, repository_key: str, event_id: str) -> None:
    user_ids = project_repository_event_access(
        database,
        repository_key=repository_key,
        event_id=event_id,
    )
    project_event_for_audience(database, event_id=event_id, user_ids=user_ids)
    security = SecurityProjector(database)
    for user_id in user_ids:
        security.project_event_for_user(user_id=user_id, event_id=event_id)


async def crawl_sbom_security_events(
    settings: Settings,
    database: Database,
    *,
    owner: str,
    repository: str,
    retrieved_at: str,
    token: str | None = None,
) -> DependencySecurityIngestResult:
    sbom_response = await fetch_github_sbom(
        settings,
        owner=owner,
        repository=repository,
        token=token,
    )
    packages = extract_osv_packages(sbom_response)
    batch_results = await query_osv_batch(settings, packages)
    return ingest_sbom_security_events(
        database,
        owner=owner,
        repository=repository,
        sbom_response=sbom_response,
        batch_results=batch_results,
        retrieved_at=retrieved_at,
    )


def _timestamp(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
