from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.database import Database
from app.db.release_lifecycle import worker_is_fresh

DEFAULT_STALE_AFTER_SECONDS = 600
Visibility = Literal["public", "private", "unknown"]
HeartbeatState = Literal["ok", "stale"]
FreshnessState = Literal["ok", "stale", "failing"]


@dataclass(frozen=True)
class SourceHealth:
    source_type: str
    source_key: str
    last_attempt_at: int | None
    last_success_at: int | None
    last_new_observation_at: int | None
    failure_count: int
    next_run_at: int
    visibility: Visibility

    def is_failing(self) -> bool:
        return self.failure_count > 0

    def is_stale(self, *, now: int, stale_after_seconds: int) -> bool:
        if self.last_success_at is None:
            return True
        return now - self.last_success_at > stale_after_seconds


@dataclass(frozen=True)
class SourceHealthSummary:
    configured: int
    fresh: int
    stale: int
    failing: int
    private_or_unknown: int
    worker_heartbeat: HeartbeatState
    source_freshness: FreshnessState

    def as_public_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "fresh": self.fresh,
            "stale": self.stale,
            "failing": self.failing,
            "privateOrUnknown": self.private_or_unknown,
            "status": self.source_freshness,
        }


def source_visibility(
    connection,
    *,
    source_type: str,
    source_key: str,
) -> Visibility:
    if source_type not in {"github_release", "dependency_security"}:
        return "unknown"
    rows = connection.execute(
        """
        SELECT private
        FROM github_repo_watches
        WHERE full_name = ?
        """,
        (source_key,),
    ).fetchall()
    if not rows:
        return "unknown"
    if any(int(row["private"]) for row in rows):
        return "private"
    return "public"


def list_source_health(database: Database) -> tuple[SourceHealth, ...]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT source_type, source_key, last_attempt_at, last_success_at,
                   last_new_observation_at, failure_count, next_run_at
            FROM source_sync_jobs
            ORDER BY source_type, source_key
            """
        ).fetchall()
        return tuple(
            SourceHealth(
                source_type=row["source_type"],
                source_key=row["source_key"],
                last_attempt_at=row["last_attempt_at"],
                last_success_at=row["last_success_at"],
                last_new_observation_at=row["last_new_observation_at"],
                failure_count=int(row["failure_count"]),
                next_run_at=int(row["next_run_at"]),
                visibility=source_visibility(
                    connection,
                    source_type=row["source_type"],
                    source_key=row["source_key"],
                ),
            )
            for row in rows
        )


def summarize_source_health(
    database: Database,
    *,
    now: int,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> SourceHealthSummary:
    records = list_source_health(database)
    stale = 0
    failing = 0
    private_or_unknown = 0
    for record in records:
        if record.visibility != "public":
            private_or_unknown += 1
        if record.is_failing():
            failing += 1
        if record.is_stale(now=now, stale_after_seconds=stale_after_seconds):
            stale += 1
    configured = len(records)
    fresh = configured - stale
    if failing:
        freshness: FreshnessState = "failing"
    elif stale:
        freshness = "stale"
    else:
        freshness = "ok"
    return SourceHealthSummary(
        configured=configured,
        fresh=fresh,
        stale=stale,
        failing=failing,
        private_or_unknown=private_or_unknown,
        worker_heartbeat="ok" if worker_is_fresh(database, now=now) else "stale",
        source_freshness=freshness,
    )
