from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database import Database


class SecurityProjector:
    """Project repo-scoped dependency vulnerability Events into user security surfaces."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def project_event_for_user(self, *, user_id: str, event_id: str) -> str | None:
        with self._database.connect() as connection:
            watch = connection.execute(
                """
                SELECT repository_id, full_name
                FROM github_repo_watches
                WHERE user_id = ? AND selected = 1
                  AND full_name = (SELECT source_key FROM ledger_events WHERE id = ?)
                LIMIT 1
                """,
                (user_id, event_id),
            ).fetchone()
            if watch is None:
                return None

            row = connection.execute(
                """
                SELECT c.id AS claim_id, c.valid_at, c.detail_text, c.value_text,
                       c.source_updated_at, r.relation_type, o.payload_json
                FROM state_claims c
                JOIN claim_relations r ON r.new_claim_id = c.id
                JOIN observations o ON o.id = c.observation_id
                WHERE c.event_id = ?
                  AND c.slot = 'dependency_vulnerability'
                  AND r.relation_type != 'UNRESOLVED_CONTRADICTION'
                ORDER BY c.valid_at DESC, c.source_updated_at DESC, c.id DESC
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None

            latest_payload = json.loads(row["payload_json"])
            metadata_payload = _metadata_payload(connection, event_id)
            if metadata_payload is None:
                return None
            vulnerability = metadata_payload["vulnerability"]
            dependency = metadata_payload["dependency"]

            advisory_id = _text(vulnerability.get("id"))
            package_name = _text(dependency.get("name"))
            previous_version = _text(dependency.get("version"))
            if not advisory_id or not package_name or not previous_version:
                return None

            current_version = _query_version(latest_payload) or previous_version
            severity = _severity(vulnerability)
            fixed_version = _fixed_version(vulnerability)
            summary = row["detail_text"] or _text(vulnerability.get("summary"))
            alert_id = _stable_id("alert", f"{user_id}|{event_id}")
            resolved = row["value_text"] == "fixed"
            projected_status = "resolved" if resolved else "open"
            if resolved:
                recommendation = f"{advisory_id} is no longer active for the current repository SBOM."
                evidence = (
                    f"The latest {watch['full_name']} SBOM/OSV reconciliation no longer reports "
                    f"{package_name} {current_version} as affected by {advisory_id}."
                )
            else:
                recommendation = (
                    f"Upgrade {package_name} to {fixed_version} or later."
                    if fixed_version
                    else f"Review {advisory_id} and update or mitigate {package_name}."
                )
                evidence = (
                    f"{watch['full_name']} depends on {package_name} {current_version}; "
                    f"{advisory_id} reports that version as affected."
                )
            connection.execute(
                """
                INSERT INTO security_alerts (
                    id, user_id, advisory_id, cve, title, summary, severity, status,
                    repository_id, repository_full_name, package_name, current_version,
                    fixed_version, dependency_type, detected_at, source, evidence,
                    recommendation, cvss_score
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'direct', ?,
                    'OSV + GitHub SBOM', ?, ?, NULL
                )
                ON CONFLICT(id) DO UPDATE SET
                    advisory_id = excluded.advisory_id,
                    cve = excluded.cve,
                    title = excluded.title,
                    summary = excluded.summary,
                    severity = excluded.severity,
                    status = CASE
                        WHEN excluded.status = 'resolved' THEN 'resolved'
                        WHEN security_alerts.status IN ('resolved', 'not_affected') THEN excluded.status
                        ELSE security_alerts.status
                    END,
                    repository_id = excluded.repository_id,
                    repository_full_name = excluded.repository_full_name,
                    package_name = excluded.package_name,
                    current_version = excluded.current_version,
                    fixed_version = excluded.fixed_version,
                    dependency_type = excluded.dependency_type,
                    source = excluded.source,
                    evidence = excluded.evidence,
                    recommendation = excluded.recommendation
                """,
                (
                    alert_id,
                    user_id,
                    advisory_id,
                    _cve(vulnerability),
                    f"{package_name} {current_version} — {advisory_id}",
                    summary,
                    severity,
                    projected_status,
                    watch["repository_id"],
                    watch["full_name"],
                    package_name,
                    current_version,
                    fixed_version,
                    row["valid_at"],
                    evidence,
                    recommendation,
                ),
            )

            if row["relation_type"] == "NON_NOVEL":
                return alert_id

            notification_id = _stable_id("ntf", f"{user_id}|{row['claim_id']}")
            priority = "normal" if resolved else "urgent" if severity == "critical" else "high"
            notification_title = (
                f"Security resolved: {package_name}"
                if resolved
                else f"Security update: {package_name}"
            )
            connection.execute(
                """
                INSERT INTO notifications (
                    id, user_id, title, summary, category, priority, occurred_at,
                    target_type, target_id, read
                ) VALUES (?, ?, ?, ?, 'security', ?, ?, 'security_alert', ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    category = excluded.category,
                    priority = excluded.priority,
                    occurred_at = excluded.occurred_at,
                    target_type = excluded.target_type,
                    target_id = excluded.target_id
                """,
                (
                    notification_id,
                    user_id,
                    notification_title,
                    summary,
                    priority,
                    row["valid_at"],
                    alert_id,
                ),
            )
            return alert_id


def _metadata_payload(connection, event_id: str) -> dict[str, dict[str, Any]] | None:
    rows = connection.execute(
        """
        SELECT o.payload_json
        FROM state_claims c
        JOIN observations o ON o.id = c.observation_id
        WHERE c.event_id = ? AND c.slot = 'dependency_vulnerability'
        ORDER BY c.valid_at DESC, c.source_updated_at DESC, c.id DESC
        """,
        (event_id,),
    ).fetchall()
    for row in rows:
        payload = json.loads(row["payload_json"])
        vulnerability = payload.get("vulnerability")
        dependency = payload.get("dependency")
        if isinstance(vulnerability, dict) and isinstance(dependency, dict):
            return {"vulnerability": vulnerability, "dependency": dependency}
    return None


def _query_version(payload: dict[str, Any]) -> str:
    query = payload.get("query")
    if not isinstance(query, dict):
        return ""
    return _text(query.get("version"))


def _severity(vulnerability: dict[str, Any]) -> str:
    candidates: list[object] = [vulnerability.get("severity")]
    database_specific = vulnerability.get("database_specific")
    if isinstance(database_specific, dict):
        candidates.append(database_specific.get("severity"))
    for value in candidates:
        if isinstance(value, str):
            normalized = value.casefold()
            if normalized in {"critical", "high", "medium", "low"}:
                return normalized
            if normalized == "moderate":
                return "medium"
    return "medium"


def _fixed_version(vulnerability: dict[str, Any]) -> str:
    affected = vulnerability.get("affected")
    if not isinstance(affected, list):
        return ""
    for entry in affected:
        if not isinstance(entry, dict):
            continue
        ranges = entry.get("ranges")
        if not isinstance(ranges, list):
            continue
        for item_range in ranges:
            if not isinstance(item_range, dict):
                continue
            events = item_range.get("events")
            if not isinstance(events, list):
                continue
            for event in events:
                if isinstance(event, dict) and isinstance(event.get("fixed"), str):
                    return event["fixed"]
    return ""


def _cve(vulnerability: dict[str, Any]) -> str | None:
    aliases = vulnerability.get("aliases")
    if not isinstance(aliases, list):
        return None
    for alias in aliases:
        if isinstance(alias, str) and alias.startswith("CVE-"):
            return alias
    return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _stable_id(prefix: str, raw: str) -> str:
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
