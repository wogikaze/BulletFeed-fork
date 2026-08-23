from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.config import Settings, get_settings
from app.database import Database
from app.security import TokenCipher
from app.services import github
from app.services.dependency_security_pipeline import crawl_sbom_security_events
from app.services.event_access import revoke_repository_access
from app.services.github_release_pipeline import crawl_github_release_events

SOURCE_TYPES = ("github_release", "dependency_security")


@dataclass(frozen=True)
class SyncJob:
    source_type: str
    repository_full_name: str
    failure_count: int
    lease_token: str


@dataclass(frozen=True)
class SyncRunSummary:
    attempted: int
    succeeded: int
    failed: int


class WatchSyncWorker:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        *,
        poll_interval_seconds: int = 300,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 3600,
        lease_seconds: int = 120,
        batch_size: int = 20,
    ) -> None:
        if min(
            poll_interval_seconds,
            retry_base_seconds,
            retry_max_seconds,
            lease_seconds,
            batch_size,
        ) < 1:
            raise ValueError("sync worker limits must be positive")
        self._settings = settings
        self._database = database
        self._poll_interval_seconds = poll_interval_seconds
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size
        self._cipher: TokenCipher | None = None
        self._cipher_error: str | None = None
        key = settings.token_encryption_key.get_secret_value()
        if key:
            try:
                self._cipher = TokenCipher(key)
            except ValueError as exc:
                self._cipher_error = str(exc)

    @property
    def batch_size(self) -> int:
        return self._batch_size

    def refresh_jobs(self, *, now: int | None = None) -> int:
        current = int(time.time()) if now is None else now
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repositories = [
                row["full_name"]
                for row in connection.execute(
                    """
                    SELECT DISTINCT full_name
                    FROM github_repo_watches
                    WHERE selected = 1
                    ORDER BY full_name
                    """
                ).fetchall()
            ]
            for repository_full_name in repositories:
                for source_type in SOURCE_TYPES:
                    connection.execute(
                        """
                        INSERT INTO source_sync_jobs (
                            source_type, repository_full_name, next_run_at
                        ) VALUES (?, ?, ?)
                        ON CONFLICT(source_type, repository_full_name) DO NOTHING
                        """,
                        (source_type, repository_full_name, current),
                    )
            connection.execute(
                """
                DELETE FROM source_sync_jobs
                WHERE lease_until <= ?
                  AND repository_full_name NOT IN (
                      SELECT DISTINCT full_name
                      FROM github_repo_watches
                      WHERE selected = 1
                  )
                """,
                (current,),
            )
            connection.commit()
        return len(repositories)

    def claim_due(self, *, now: int | None = None, limit: int | None = None) -> list[SyncJob]:
        current = int(time.time()) if now is None else now
        claim_limit = self._batch_size if limit is None else max(1, min(limit, self._batch_size))
        claimed: list[SyncJob] = []
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT source_type, repository_full_name, failure_count
                FROM source_sync_jobs
                WHERE next_run_at <= ? AND lease_until <= ?
                ORDER BY next_run_at, repository_full_name, source_type
                LIMIT ?
                """,
                (current, current, claim_limit),
            ).fetchall()
            lease_until = current + self._lease_seconds
            for row in rows:
                lease_token = secrets.token_urlsafe(18)
                changed = connection.execute(
                    """
                    UPDATE source_sync_jobs
                    SET lease_until = ?, lease_token = ?, last_attempt_at = ?
                    WHERE source_type = ? AND repository_full_name = ?
                      AND lease_until <= ?
                    """,
                    (
                        lease_until,
                        lease_token,
                        current,
                        row["source_type"],
                        row["repository_full_name"],
                        current,
                    ),
                ).rowcount
                if changed == 1:
                    claimed.append(
                        SyncJob(
                            source_type=row["source_type"],
                            repository_full_name=row["repository_full_name"],
                            failure_count=row["failure_count"],
                            lease_token=lease_token,
                        )
                    )
            connection.commit()
        return claimed

    async def run_once(self, *, now: int | None = None) -> SyncRunSummary:
        scheduled_at = int(time.time()) if now is None else now
        self.refresh_jobs(now=scheduled_at)
        attempted = 0
        succeeded = 0
        failed = 0
        while attempted < self._batch_size:
            job_started_at = int(time.time()) if now is None else scheduled_at
            jobs = self.claim_due(now=job_started_at, limit=1)
            if not jobs:
                break
            job = jobs[0]
            attempted += 1
            try:
                await self._run_with_lease_heartbeat(job, now=job_started_at)
            except Exception as exc:
                finished_at = int(time.time()) if now is None else scheduled_at
                self._finish_failure(job, exc, now=finished_at)
                failed += 1
            else:
                finished_at = int(time.time()) if now is None else scheduled_at
                self._finish_success(job, now=finished_at)
                succeeded += 1
        return SyncRunSummary(attempted=attempted, succeeded=succeeded, failed=failed)

    async def _run_with_lease_heartbeat(self, job: SyncJob, *, now: int) -> None:
        heartbeat = asyncio.create_task(self._lease_heartbeat(job))
        try:
            await self._run_job(job, now=now)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _lease_heartbeat(self, job: SyncJob) -> None:
        interval = max(self._lease_seconds / 3, 1.0)
        while True:
            await asyncio.sleep(interval)
            self._extend_lease(job, now=int(time.time()))

    def _extend_lease(self, job: SyncJob, *, now: int) -> bool:
        with self._database.connect() as connection:
            changed = connection.execute(
                """
                UPDATE source_sync_jobs
                SET lease_until = ?
                WHERE source_type = ? AND repository_full_name = ? AND lease_token = ?
                """,
                (
                    now + self._lease_seconds,
                    job.source_type,
                    job.repository_full_name,
                    job.lease_token,
                ),
            ).rowcount
        return changed == 1

    async def _run_job(self, job: SyncJob, *, now: int) -> None:
        owner, separator, repository = job.repository_full_name.partition("/")
        if not separator or not owner or not repository or "/" in repository:
            raise ValueError("repository watch must use owner/repository format")
        await self._refresh_repository_authorizations(
            repository_full_name=job.repository_full_name,
            owner=owner,
            repository=repository,
            now=now,
        )
        if not self._repository_has_selected_watch(job.repository_full_name):
            return
        token = self._repository_token(job.repository_full_name, now=now)
        retrieved_at = datetime.fromtimestamp(now, tz=UTC).isoformat().replace("+00:00", "Z")
        if job.source_type == "github_release":
            await crawl_github_release_events(
                self._settings,
                self._database,
                owner=owner,
                repository=repository,
                retrieved_at=retrieved_at,
                token=token,
            )
            return
        if job.source_type == "dependency_security":
            await crawl_sbom_security_events(
                self._settings,
                self._database,
                owner=owner,
                repository=repository,
                retrieved_at=retrieved_at,
                token=token,
            )
            return
        raise ValueError(f"unsupported source sync type: {job.source_type}")

    async def _refresh_repository_authorizations(
        self,
        *,
        repository_full_name: str,
        owner: str,
        repository: str,
        now: int,
    ) -> None:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT w.user_id, u.github_user_id, c.github_token_encrypted, c.token_expires_at
                FROM github_repo_watches w
                JOIN users u ON u.id = w.user_id
                LEFT JOIN github_connections c ON c.github_user_id = u.github_user_id
                WHERE w.full_name = ? AND w.selected = 1
                ORDER BY w.user_id
                """,
                (repository_full_name,),
            ).fetchall()
        for row in rows:
            # Unit fixtures and imported legacy rows may not be bound to GitHub yet.
            # Real connected watches always have github_user_id and fail closed below.
            if row["github_user_id"] is None:
                continue
            encrypted = row["github_token_encrypted"]
            expires_at = row["token_expires_at"]
            if encrypted is None or (expires_at is not None and expires_at <= now):
                self._revoke_watch(row["user_id"], repository_full_name)
                continue
            if self._cipher is None:
                detail = self._cipher_error or "token encryption key is not configured"
                raise RuntimeError(detail)
            token = self._cipher.decrypt(encrypted)
            metadata = await github.repository_accessible(
                self._settings,
                owner,
                repository,
                token,
            )
            if metadata is None:
                self._revoke_watch(row["user_id"], repository_full_name)
                continue
            with self._database.connect() as connection:
                connection.execute(
                    """
                    UPDATE github_repo_watches
                    SET private = ?
                    WHERE user_id = ? AND full_name = ?
                    """,
                    (int(bool(metadata.get("private"))), row["user_id"], repository_full_name),
                )

    def _revoke_watch(self, user_id: str, repository_full_name: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE github_repo_watches
                SET selected = 0
                WHERE user_id = ? AND full_name = ?
                """,
                (user_id, repository_full_name),
            )
        revoke_repository_access(
            self._database,
            user_id=user_id,
            repository_key=repository_full_name,
        )

    def _repository_has_selected_watch(self, repository_full_name: str) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM github_repo_watches WHERE full_name = ? AND selected = 1 LIMIT 1",
                (repository_full_name,),
            ).fetchone()
        return row is not None

    def _repository_token(self, repository_full_name: str, *, now: int) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT c.github_token_encrypted
                FROM github_repo_watches w
                JOIN users u ON u.id = w.user_id
                JOIN github_connections c ON c.github_user_id = u.github_user_id
                WHERE w.full_name = ? AND w.selected = 1
                  AND (c.token_expires_at IS NULL OR c.token_expires_at > ?)
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                (repository_full_name, now),
            ).fetchone()
        if row is None:
            return None
        if self._cipher is None:
            detail = self._cipher_error or "token encryption key is not configured"
            raise RuntimeError(detail)
        return self._cipher.decrypt(row["github_token_encrypted"])

    def _finish_success(self, job: SyncJob, *, now: int) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE source_sync_jobs
                SET next_run_at = ?, lease_until = 0, lease_token = NULL, failure_count = 0,
                    last_success_at = ?, last_error = NULL
                WHERE source_type = ? AND repository_full_name = ? AND lease_token = ?
                """,
                (
                    now + self._poll_interval_seconds,
                    now,
                    job.source_type,
                    job.repository_full_name,
                    job.lease_token,
                ),
            )

    def _finish_failure(self, job: SyncJob, exc: Exception, *, now: int) -> None:
        failure_count = job.failure_count + 1
        exponent = min(failure_count - 1, 16)
        retry_seconds = min(
            self._retry_base_seconds * (2**exponent),
            self._retry_max_seconds,
        )
        detail = f"{type(exc).__name__}: {exc}"[:500]
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE source_sync_jobs
                SET next_run_at = ?, lease_until = 0, lease_token = NULL,
                    failure_count = ?, last_error = ?
                WHERE source_type = ? AND repository_full_name = ? AND lease_token = ?
                """,
                (
                    now + retry_seconds,
                    failure_count,
                    detail,
                    job.source_type,
                    job.repository_full_name,
                    job.lease_token,
                ),
            )


async def run_forever(worker: WatchSyncWorker, *, idle_sleep_seconds: float = 5.0) -> None:
    if idle_sleep_seconds <= 0:
        raise ValueError("idle sleep must be positive")
    while True:
        summary = await worker.run_once()
        if summary.attempted:
            print(json.dumps(asdict(summary), sort_keys=True), flush=True)
        if summary.attempted < worker.batch_size:
            await asyncio.sleep(idle_sleep_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize GitHub sources for selected repositories")
    parser.add_argument("--once", action="store_true", help="Run one due-job batch and exit")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--idle-sleep-seconds", type=float, default=5.0)
    args = parser.parse_args()

    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    worker = WatchSyncWorker(
        settings,
        database,
        poll_interval_seconds=args.poll_seconds,
        batch_size=args.batch_size,
    )
    if args.once:
        summary = asyncio.run(worker.run_once())
        print(json.dumps(asdict(summary), sort_keys=True))
        return
    asyncio.run(run_forever(worker, idle_sleep_seconds=args.idle_sleep_seconds))


if __name__ == "__main__":
    main()
