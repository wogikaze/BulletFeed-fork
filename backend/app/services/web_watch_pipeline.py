"""Production generic_web watch: snapshot → normalize → change → Observation/Claim.

generic_web remains discovery-only. Claims are minted only when the registry
already lists the URL as official_changelog or documentation. Does not start
#64 rendering. Unchanged / HTTP 304 bodies do not create Observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.services.source_registry import SourceRegistry, canonicalize_url
from app.services.web_changes import extract_web_snapshot_changes
from app.services.web_claims import WebClaimIngestResult, ingest_web_changeset
from app.services.web_snapshots import SnapshotStore, WebSnapshot, fetch_web_snapshot


def web_snapshot_store(settings: Settings) -> SnapshotStore:
    root = Path(settings.database_path).resolve().parent / "web_snapshots"
    return SnapshotStore(root)


def _audience_user_ids(database: Database, *, source_type: str, source_key: str) -> tuple[str, ...]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT user_id
            FROM source_sync_subscription_users
            WHERE source_type = ? AND source_key = ?
            ORDER BY user_id
            """,
            (source_type, source_key),
        ).fetchall()
    return tuple(str(row["user_id"]) for row in rows)


@dataclass(frozen=True)
class WebWatchCrawlResult:
    snapshot: WebSnapshot
    unchanged: bool
    ingest: WebClaimIngestResult | None


async def crawl_web_watch(
    settings: Settings,
    database: Database,
    *,
    url: str,
    retrieved_at: str,
    store: SnapshotStore | None = None,
    registry: SourceRegistry | None = None,
) -> WebWatchCrawlResult:
    snapshot_store = store or web_snapshot_store(settings)
    canonical = canonicalize_url(url)
    previous = snapshot_store.latest_for(canonical)
    snapshot = await fetch_web_snapshot(
        settings,
        url,
        store=snapshot_store,
        retrieved_at=retrieved_at,
        previous=previous,
    )
    if snapshot.not_modified or (
        previous is not None and snapshot.content_hash == previous.content_hash
    ):
        return WebWatchCrawlResult(snapshot=snapshot, unchanged=True, ingest=None)
    if previous is None:
        return WebWatchCrawlResult(snapshot=snapshot, unchanged=False, ingest=None)

    changeset = extract_web_snapshot_changes(previous, snapshot)
    if not changeset.downstream_candidates:
        return WebWatchCrawlResult(snapshot=snapshot, unchanged=True, ingest=None)

    source_registry = registry or SourceRegistry(database)
    audience = _audience_user_ids(
        database,
        source_type="generic_web",
        source_key=canonical,
    )
    ingest = ingest_web_changeset(
        database,
        changeset,
        left_snapshot=previous,
        right_snapshot=snapshot,
        registry=source_registry,
        retrieved_at=retrieved_at,
        project=True,
        audience_user_ids=audience,
    )
    return WebWatchCrawlResult(snapshot=snapshot, unchanged=False, ingest=ingest)


def utc_stamp(now: int) -> str:
    return datetime.fromtimestamp(now, tz=UTC).isoformat().replace("+00:00", "Z")
