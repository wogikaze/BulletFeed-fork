from __future__ import annotations

import base64
import binascii
import time

from fastapi import HTTPException, status

from app.config import Settings
from app.database import Database
from app.errors import not_found, unprocessable
from app.schemas.integrations import (
    GithubConnection,
    GithubImportResult,
    GithubRepository,
    GithubRepositoryPage,
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
                    connection.execute("DELETE FROM app_sessions WHERE github_user_id = ?", (github_user_id,))
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
