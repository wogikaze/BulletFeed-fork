from __future__ import annotations

import base64
import binascii
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, status

from app.config import Settings
from app.database import Database
from app.errors import not_found, unprocessable
from app.schemas.integrations import (
    GithubConnection,
    GithubImportResult,
    GithubRepository,
    GithubRepositoryPage,
    GithubTopicSyncStatus,
    NotificationItem,
    NotificationTarget,
    SecurityAlert,
    SecurityAlertPackage,
    SecurityAlertRepository,
)
from app.security import TokenCipher
from app.services import github
from app.services.event_access import revoke_repository_access
from app.stores.me_store import MeStore

_ALERT_STATUSES = {"open", "in_progress", "resolved", "not_affected"}


@dataclass(frozen=True)
class GithubTopicSyncJob:
    user_id: str
    generation: int
    attempt_count: int
    lease_token: str


def _encode_cursor(updated_at: str, repository_id: str) -> str:
    raw = f"{updated_at}|{repository_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    padding = "=" * (-len(cursor) % 4)
    try:
        value = base64.urlsafe_b64decode(cursor + padding).decode()
        updated_at, repository_id = value.split("|", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise unprocessable("cursor is invalid") from exc
    if not updated_at or not repository_id:
        raise unprocessable("cursor is invalid")
    return updated_at, repository_id


def _repository_sort_key(item: GithubRepository) -> tuple[str, str]:
    return (item.updated_at, item.id)


def _activity_timestamp(repo: dict) -> str | None:
    for key in ("pushed_at", "updated_at"):
        value = repo.get(key)
        if isinstance(value, str) and value:
            return value
    return None


class IntegrationStore:
    def __init__(self, database: Database, cipher: TokenCipher) -> None:
        self._database = database
        self._cipher = cipher
        self._me_store = MeStore(database)

    def _mark_reauthorization_required(self, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET github_credential_state = 'reauthorization_required'
                WHERE id = ? AND github_user_id IS NOT NULL
                """,
                (user_id,),
            )

    def _get_github_token(self, user_id: str, *, required: bool = False) -> str | None:
        now = int(time.time())
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT u.github_user_id, u.github_credential_state,
                       c.github_token_encrypted, c.token_expires_at
                FROM users u
                LEFT JOIN github_connections c ON u.github_user_id = c.github_user_id
                WHERE u.id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None or row["github_user_id"] is None:
            if required:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="GitHub is not connected",
                )
            return None
        encrypted = row["github_token_encrypted"]
        expires_at = row["token_expires_at"]
        if encrypted is None or (expires_at is not None and expires_at <= now):
            self._mark_reauthorization_required(user_id)
            if required:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="GitHub reauthorization is required",
                )
            return None
        return self._cipher.decrypt(encrypted)

    def github_connection(self, user_id: str) -> GithubConnection:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT github_user_id, github_login, github_credential_state
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return GithubConnection(connected=False, credential_state="disconnected")
        connected = row["github_user_id"] is not None
        state = row["github_credential_state"] if connected else "disconnected"
        return GithubConnection(
            connected=connected,
            credential_state=state,
            account_login=row["github_login"],
        )

    async def list_repositories(
        self,
        user_id: str,
        query: str | None,
        cursor: str | None,
        limit: int,
        settings: Settings,
    ) -> GithubRepositoryPage:
        if limit < 1 or limit > 50:
            raise unprocessable("limit must be 1-50")
        cursor_value = _decode_cursor(cursor) if cursor else None
        github_token = self._get_github_token(user_id, required=True)
        try:
            remote = await github.list_repositories(settings, github_token)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                self._mark_reauthorization_required(user_id)
            raise

        with self._database.connect() as connection:
            selected = {
                row["repository_id"]
                for row in connection.execute(
                    "SELECT repository_id FROM github_repo_watches WHERE user_id = ? AND selected = 1",
                    (user_id,),
                )
            }
        items = []
        for repo in remote:
            try:
                repo_id = str(repo["id"])
            except (KeyError, TypeError):
                continue
            full_name = repo.get("full_name")
            html_url = repo.get("html_url")
            updated_at = _activity_timestamp(repo)
            if (
                not isinstance(full_name, str)
                or not isinstance(html_url, str)
                or updated_at is None
            ):
                continue
            if query and query.casefold() not in full_name.casefold():
                continue
            language = repo.get("language")
            items.append(
                GithubRepository(
                    id=repo_id,
                    full_name=full_name,
                    html_url=html_url,
                    private=bool(repo.get("private")),
                    description=repo.get("description") if isinstance(repo.get("description"), str) else None,
                    language=language if isinstance(language, str) else None,
                    selected=repo_id in selected,
                    updated_at=updated_at,
                )
            )
        items.sort(key=_repository_sort_key, reverse=True)
        if cursor_value is not None:
            items = [item for item in items if _repository_sort_key(item) < cursor_value]
        page = items[:limit]
        next_cursor = (
            _encode_cursor(page[-1].updated_at, page[-1].id) if len(items) > limit and page else None
        )
        return GithubRepositoryPage(items=page, next_cursor=next_cursor)

    async def update_repositories(
        self,
        user_id: str,
        repository_ids: list[str],
        settings: Settings,
    ) -> GithubConnection:
        github_token = self._get_github_token(user_id, required=True)
        try:
            remote = await github.list_repositories(settings, github_token)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                self._mark_reauthorization_required(user_id)
            raise

        known: dict[str, dict[str, object]] = {}
        for repo in remote:
            repo_id = str(repo.get("id"))
            if repo.get("full_name") and repo.get("html_url"):
                known[repo_id] = repo

        unknown = [repo_id for repo_id in repository_ids if repo_id not in known]
        if unknown:
            raise unprocessable("unknown repository id")

        with self._database.connect() as connection:
            old_repositories = {
                row["full_name"]
                for row in connection.execute(
                    "SELECT full_name FROM github_repo_watches WHERE user_id = ? AND selected = 1",
                    (user_id,),
                ).fetchall()
            }
            connection.execute("DELETE FROM github_repo_watches WHERE user_id = ?", (user_id,))
            new_repositories: set[str] = set()
            for repo_id in repository_ids:
                repo = known[repo_id]
                full_name = str(repo["full_name"])
                html_url = str(repo["html_url"])
                new_repositories.add(full_name)
                connection.execute(
                    """
                    INSERT INTO github_repo_watches (
                        user_id, repository_id, full_name, html_url, selected, private
                    ) VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (user_id, repo_id, full_name, html_url, int(bool(repo.get("private")))),
                )
            connection.execute(
                """
                UPDATE users
                SET github_connected = 1, github_credential_state = 'connected'
                WHERE id = ?
                """,
                (user_id,),
            )
        for repository_key in old_repositories - new_repositories:
            revoke_repository_access(
                self._database,
                user_id=user_id,
                repository_key=repository_key,
            )
        return self.github_connection(user_id)

    async def patch_repositories(
        self,
        user_id: str,
        add_repository_ids: list[str],
        remove_repository_ids: list[str],
        settings: Settings,
    ) -> GithubConnection:
        """Apply only the changed repository selections.

        The old full replacement endpoint remains available for compatibility,
        but the mobile client uses this delta endpoint so saving does not first
        re-fetch every repository in the user's GitHub account.
        """
        additions = set(add_repository_ids)
        removals = set(remove_repository_ids)
        if additions & removals:
            raise unprocessable("a repository cannot be added and removed together")
        if any(
            not repository_id
            or any(not (character.isalnum() or character in "-_") for character in repository_id)
            for repository_id in additions | removals
        ):
            raise unprocessable("repository id is invalid")

        github_token = self._get_github_token(user_id, required=True)
        with self._database.connect() as connection:
            existing_rows = connection.execute(
                """
                SELECT repository_id, full_name
                FROM github_repo_watches
                WHERE user_id = ? AND selected = 1
                """,
                (user_id,),
            ).fetchall()
            user_row = connection.execute(
                "SELECT onboarding_state FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        existing_ids = {row["repository_id"] for row in existing_rows}
        new_ids = (existing_ids - removals) | additions
        if user_row is not None and user_row["onboarding_state"] == "repository_pending" and not new_ids:
            raise unprocessable("select at least one GitHub repository to finish setup")

        known: dict[str, dict[str, object]] = {}
        for repository_id in additions - existing_ids:
            try:
                repo = await github.get_repository_by_id(settings, repository_id, github_token)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_403_FORBIDDEN:
                    self._mark_reauthorization_required(user_id)
                raise
            if repo is None:
                raise unprocessable("unknown repository id")
            known[repository_id] = repo

        old_names = {
            row["full_name"] for row in existing_rows if row["repository_id"] in removals
        }
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for repository_id in removals:
                connection.execute(
                    "DELETE FROM github_repo_watches WHERE user_id = ? AND repository_id = ?",
                    (user_id, repository_id),
                )
            for repository_id, repo in known.items():
                full_name = repo.get("full_name")
                html_url = repo.get("html_url")
                if not isinstance(full_name, str) or not isinstance(html_url, str):
                    raise unprocessable("GitHub returned invalid repository metadata")
                connection.execute(
                    """
                    INSERT INTO github_repo_watches (
                        user_id, repository_id, full_name, html_url, selected, private
                    ) VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(user_id, repository_id) DO UPDATE SET
                        full_name = excluded.full_name,
                        html_url = excluded.html_url,
                        selected = 1,
                        private = excluded.private
                    """,
                    (user_id, repository_id, full_name, html_url, int(bool(repo.get("private")))),
                )
            connection.execute(
                """
                UPDATE users
                SET github_connected = 1, github_credential_state = 'connected'
                WHERE id = ?
                """,
                (user_id,),
            )
            connection.commit()
        for repository_key in old_names:
            revoke_repository_access(
                self._database,
                user_id=user_id,
                repository_key=repository_key,
            )
        return self.github_connection(user_id)

    def enqueue_github_topic_sync(self, user_id: str, *, now: int | None = None) -> None:
        current = int(time.time()) if now is None else now
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO github_topic_sync_jobs (
                    user_id, generation, status, requested_at, next_run_at,
                    started_at, finished_at, lease_until, lease_token, attempt_count,
                    added_topics_json, already_tracked_topics_json,
                    inspected_repository_count, failed_repository_count, last_error
                ) VALUES (?, 1, 'pending', ?, ?, NULL, NULL, 0, NULL, 0, '[]', '[]', 0, 0, NULL)
                ON CONFLICT(user_id) DO UPDATE SET
                    generation = github_topic_sync_jobs.generation + 1,
                    status = 'pending',
                    requested_at = excluded.requested_at,
                    next_run_at = excluded.next_run_at,
                    started_at = NULL,
                    finished_at = NULL,
                    lease_until = 0,
                    lease_token = NULL,
                    attempt_count = 0,
                    added_topics_json = '[]',
                    already_tracked_topics_json = '[]',
                    inspected_repository_count = 0,
                    failed_repository_count = 0,
                    last_error = NULL
                """,
                (user_id, current, current),
            )

    def github_topic_sync_status(self, user_id: str) -> GithubTopicSyncStatus:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM github_topic_sync_jobs WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return GithubTopicSyncStatus(state="idle")
        return GithubTopicSyncStatus(
            state=row["status"],
            requested_at=row["requested_at"],
            finished_at=row["finished_at"],
            added_topics=_decode_topic_names(row["added_topics_json"]),
            already_tracked_topics=_decode_topic_names(row["already_tracked_topics_json"]),
            inspected_repository_count=int(row["inspected_repository_count"]),
            failed_repository_count=int(row["failed_repository_count"]),
            error=row["last_error"],
        )

    def claim_github_topic_sync_jobs(
        self,
        *,
        now: int | None = None,
        limit: int = 1,
        lease_seconds: int = 120,
    ) -> list[GithubTopicSyncJob]:
        current = int(time.time()) if now is None else now
        claimed: list[GithubTopicSyncJob] = []
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE github_topic_sync_jobs
                SET status = 'failed', next_run_at = ?, lease_until = 0,
                    lease_token = NULL, last_error = 'previous worker lease expired'
                WHERE status = 'running' AND lease_until <= ?
                """,
                (current, current),
            )
            rows = connection.execute(
                """
                SELECT user_id, generation, attempt_count
                FROM github_topic_sync_jobs
                WHERE status IN ('pending', 'failed')
                  AND next_run_at <= ? AND lease_until <= ?
                ORDER BY next_run_at, requested_at, user_id
                LIMIT ?
                """,
                (current, current, max(1, limit)),
            ).fetchall()
            for row in rows:
                lease_token = secrets.token_urlsafe(18)
                changed = connection.execute(
                    """
                    UPDATE github_topic_sync_jobs
                    SET status = 'running', started_at = ?, lease_until = ?,
                        lease_token = ?, attempt_count = attempt_count + 1
                    WHERE user_id = ? AND generation = ?
                      AND status IN ('pending', 'failed') AND lease_until <= ?
                    """,
                    (
                        current,
                        current + lease_seconds,
                        lease_token,
                        row["user_id"],
                        row["generation"],
                        current,
                    ),
                ).rowcount
                if changed == 1:
                    claimed.append(
                        GithubTopicSyncJob(
                            user_id=row["user_id"],
                            generation=int(row["generation"]),
                            attempt_count=int(row["attempt_count"]) + 1,
                            lease_token=lease_token,
                        )
                    )
            connection.commit()
        return claimed

    def extend_github_topic_sync_lease(
        self,
        job: GithubTopicSyncJob,
        *,
        now: int | None = None,
        lease_seconds: int = 120,
    ) -> bool:
        current = int(time.time()) if now is None else now
        with self._database.connect() as connection:
            changed = connection.execute(
                """
                UPDATE github_topic_sync_jobs
                SET lease_until = ?
                WHERE user_id = ? AND generation = ? AND status = 'running'
                  AND lease_token = ?
                """,
                (current + lease_seconds, job.user_id, job.generation, job.lease_token),
            ).rowcount
        return changed == 1

    def finish_github_topic_sync_success(
        self,
        job: GithubTopicSyncJob,
        *,
        added_topics: list[str],
        already_tracked_topics: list[str],
        inspected_repository_count: int,
        failed_repository_count: int,
        now: int | None = None,
    ) -> bool:
        current = int(time.time()) if now is None else now
        with self._database.connect() as connection:
            changed = connection.execute(
                """
                UPDATE github_topic_sync_jobs
                SET status = 'completed', finished_at = ?, lease_until = 0,
                    lease_token = NULL, next_run_at = ?,
                    added_topics_json = ?, already_tracked_topics_json = ?,
                    inspected_repository_count = ?, failed_repository_count = ?,
                    last_error = NULL
                WHERE user_id = ? AND generation = ? AND status = 'running'
                  AND lease_token = ?
                """,
                (
                    current,
                    current,
                    json.dumps(added_topics, ensure_ascii=False),
                    json.dumps(already_tracked_topics, ensure_ascii=False),
                    inspected_repository_count,
                    failed_repository_count,
                    job.user_id,
                    job.generation,
                    job.lease_token,
                ),
            ).rowcount
        return changed == 1

    def finish_github_topic_sync_failure(
        self,
        job: GithubTopicSyncJob,
        error: Exception,
        *,
        now: int | None = None,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 3600,
    ) -> bool:
        current = int(time.time()) if now is None else now
        retry_seconds = min(
            retry_base_seconds * (2 ** min(job.attempt_count - 1, 16)),
            retry_max_seconds,
        )
        detail = f"{type(error).__name__}: {error}"[:500]
        with self._database.connect() as connection:
            changed = connection.execute(
                """
                UPDATE github_topic_sync_jobs
                SET status = 'failed', next_run_at = ?, lease_until = 0,
                    lease_token = NULL, last_error = ?
                WHERE user_id = ? AND generation = ? AND status = 'running'
                  AND lease_token = ?
                """,
                (current + retry_seconds, detail, job.user_id, job.generation, job.lease_token),
            ).rowcount
        return changed == 1

    async def import_repository_keywords(
        self,
        user_id: str,
        full_name: str,
        settings: Settings,
    ) -> GithubImportResult:
        stripped = full_name.strip()
        parts = stripped.split("/")
        if len(parts) != 2 or not all(parts):
            raise unprocessable("full_name must be in owner/repo format")
        owner, repo = parts
        github_token = self._get_github_token(user_id)
        languages = await github.get_repository_languages(settings, owner, repo, github_token)
        topics = await github.get_repository_topics(settings, owner, repo, github_token)

        sorted_languages = [
            name for name, _ in sorted(languages.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        selected_topics = topics[:10]
        keywords = list(dict.fromkeys(sorted_languages + selected_topics))

        existing = {topic.name.lower() for topic in self._me_store.list_topics(user_id)}
        added: list[str] = []
        for keyword in keywords:
            if keyword.lower() in existing:
                continue
            if len(existing) >= 20:
                break
            try:
                self._me_store.add_topic(user_id, keyword, "technology")
                existing.add(keyword.lower())
                added.append(keyword)
            except HTTPException as exc:
                if exc.status_code == 409:
                    continue
                if exc.status_code == 422:
                    break
                raise
        return GithubImportResult(full_name=stripped, keywords=keywords, added_topics=added)

    def disconnect_github(self, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = connection.execute(
                "SELECT github_user_id FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            github_user_id = user["github_user_id"] if user is not None else None
            repositories = [
                row["full_name"]
                for row in connection.execute(
                    "SELECT full_name FROM github_repo_watches WHERE user_id = ? AND selected = 1",
                    (user_id,),
                ).fetchall()
            ]
            connection.execute("DELETE FROM github_inferred_signals WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM github_topic_sync_jobs WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM github_repo_watches WHERE user_id = ?", (user_id,))
            connection.execute(
                """
                UPDATE users
                SET github_connected = 0,
                    github_credential_state = 'disconnected',
                    github_user_id = NULL,
                    github_login = NULL
                WHERE id = ?
                """,
                (user_id,),
            )
            if github_user_id is not None:
                remaining = connection.execute(
                    "SELECT 1 FROM users WHERE github_user_id = ? LIMIT 1",
                    (github_user_id,),
                ).fetchone()
                if remaining is None:
                    connection.execute(
                        "DELETE FROM github_connections WHERE github_user_id = ?",
                        (github_user_id,),
                    )
            connection.commit()
        for repository_key in repositories:
            revoke_repository_access(
                self._database,
                user_id=user_id,
                repository_key=repository_key,
            )

    def list_alerts(
        self, user_id: str, alert_status: str | None, repository_id: str | None
    ) -> list[SecurityAlert]:
        if alert_status is not None and alert_status not in _ALERT_STATUSES:
            raise unprocessable("status is invalid")
        with self._database.connect() as connection:
            fetched = connection.execute(
                """
                SELECT * FROM security_alerts
                WHERE user_id = ?
                ORDER BY detected_at DESC
                """,
                (user_id,),
            ).fetchall()
        rows = [
            row
            for row in fetched
            if (alert_status is None or row["status"] == alert_status)
            and (repository_id is None or row["repository_id"] == repository_id)
        ]
        return [_alert_from_row(row) for row in rows]

    def get_alert(self, user_id: str, alert_id: str) -> SecurityAlert:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM security_alerts WHERE id = ? AND user_id = ?",
                (alert_id, user_id),
            ).fetchone()
        if row is None:
            raise not_found("Alert was not found")
        return _alert_from_row(row)

    def patch_alert(self, user_id: str, alert_id: str, alert_status: str) -> SecurityAlert:
        with self._database.connect() as connection:
            changed = connection.execute(
                "UPDATE security_alerts SET status = ? WHERE id = ? AND user_id = ?",
                (alert_status, alert_id, user_id),
            ).rowcount
        if changed == 0:
            raise not_found("Alert was not found")
        return self.get_alert(user_id, alert_id)

    def list_notifications(self, user_id: str, only_unread: bool) -> list[NotificationItem]:
        with self._database.connect() as connection:
            sql = "SELECT * FROM notifications WHERE user_id = ?"
            params: list[object] = [user_id]
            if only_unread:
                sql += " AND read = 0"
            sql += " ORDER BY occurred_at DESC"
            rows = connection.execute(sql, params).fetchall()
        return [_notification_from_row(row) for row in rows]

    def mark_notification_read(self, user_id: str, notification_id: str) -> NotificationItem:
        with self._database.connect() as connection:
            changed = connection.execute(
                "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
                (notification_id, user_id),
            ).rowcount
            if changed == 0:
                raise not_found("Notification was not found")
            row = connection.execute(
                "SELECT * FROM notifications WHERE id = ? AND user_id = ?",
                (notification_id, user_id),
            ).fetchone()
        return _notification_from_row(row)

    def mark_all_notifications_read(self, user_id: str) -> int:
        with self._database.connect() as connection:
            changed = connection.execute(
                "UPDATE notifications SET read = 1 WHERE user_id = ? AND read = 0",
                (user_id,),
            ).rowcount
        return changed


def _alert_from_row(row) -> SecurityAlert:
    return SecurityAlert(
        id=row["id"],
        advisory_id=row["advisory_id"],
        cve=row["cve"],
        title=row["title"],
        summary=row["summary"],
        severity=row["severity"],
        status=row["status"],
        repository=SecurityAlertRepository(
            id=row["repository_id"] or "",
            full_name=row["repository_full_name"],
        ),
        package=SecurityAlertPackage(
            name=row["package_name"],
            current_version=row["current_version"],
            fixed_version=row["fixed_version"] or "",
            dependency_type=row["dependency_type"],
        ),
        source=row["source"],
        detected_at=row["detected_at"],
        evidence=row["evidence"],
        recommendation=row["recommendation"],
        cvss_score=row["cvss_score"],
    )


def _notification_from_row(row) -> NotificationItem:
    return NotificationItem(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        category=row["category"],
        priority=row["priority"],
        occurred_at=row["occurred_at"],
        read=bool(row["read"]),
        target=NotificationTarget(type=row["target_type"], id=row["target_id"]),
    )


def _decode_topic_names(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, str)]
