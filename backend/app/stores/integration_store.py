from __future__ import annotations

import base64

from fastapi import HTTPException

from app.config import Settings
from app.database import Database
from app.db.seed import seed_user_workspace
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
from app.stores.me_store import MeStore

_ALERT_STATUSES = {"open", "in_progress", "resolved", "not_affected"}


def _encode_cursor(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> str:
    padding = "=" * (-len(cursor) % 4)
    try:
        return base64.urlsafe_b64decode(cursor + padding).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise unprocessable("cursor is invalid") from exc


class IntegrationStore:
    def __init__(self, database: Database, cipher: TokenCipher) -> None:
        self._database = database
        self._cipher = cipher
        self._me_store = MeStore(database)

    def _get_github_token(self, user_id: str) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT c.github_token_encrypted
                FROM users u
                JOIN github_connections c ON u.github_user_id = c.github_user_id
                WHERE u.id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return self._cipher.decrypt(row["github_token_encrypted"])

    def github_connection(self, user_id: str) -> GithubConnection:
        with self._database.connect() as connection:
            watches = connection.execute(
                "SELECT COUNT(*) AS count FROM github_repo_watches WHERE user_id = ? AND selected = 1",
                (user_id,),
            ).fetchone()["count"]
            row = connection.execute(
                "SELECT github_connected, github_login FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return GithubConnection(connected=watches > 0)
        return GithubConnection(
            connected=bool(row["github_connected"]) or watches > 0,
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
        del cursor
        if limit < 1 or limit > 50:
            raise unprocessable("limit must be 1-50")
        github_token = self._get_github_token(user_id)
        if github_token is None:
            raise unprocessable("GitHub is not connected")
        remote = await github.list_repositories(settings, github_token)

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
            updated_at = repo.get("updated_at")
            if (
                not isinstance(full_name, str)
                or not isinstance(html_url, str)
                or not isinstance(updated_at, str)
            ):
                continue
            if query and query.lower() not in full_name.lower():
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
        items.sort(key=lambda item: item.full_name)
        page = items[:limit]
        next_cursor = _encode_cursor(page[-1].full_name) if len(items) > limit else None
        return GithubRepositoryPage(items=page, next_cursor=next_cursor)

    async def update_repositories(
        self,
        user_id: str,
        repository_ids: list[str],
        settings: Settings,
    ) -> GithubConnection:
        github_token = self._get_github_token(user_id)
        if github_token is None:
            raise unprocessable("GitHub is not connected")
        remote = await github.list_repositories(settings, github_token)

        known: dict[str, dict[str, object]] = {}
        for repo in remote:
            repo_id = str(repo.get("id"))
            if repo.get("full_name") and repo.get("html_url"):
                known[repo_id] = repo

        unknown = [repo_id for repo_id in repository_ids if repo_id not in known]
        if unknown:
            raise unprocessable("unknown repository id")

        with self._database.connect() as connection:
            connection.execute("DELETE FROM github_repo_watches WHERE user_id = ?", (user_id,))
            for repo_id in repository_ids:
                repo = known[repo_id]
                full_name = str(repo["full_name"])
                html_url = str(repo["html_url"])
                connection.execute(
                    """
                    INSERT INTO github_repo_watches (user_id, repository_id, full_name, html_url, selected)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (user_id, repo_id, full_name, html_url),
                )
            connection.execute("UPDATE users SET github_connected = 1 WHERE id = ?", (user_id,))
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
            connection.execute("DELETE FROM github_repo_watches WHERE user_id = ?", (user_id,))
            connection.execute(
                """
                UPDATE users
                SET github_connected = 0, github_user_id = NULL, github_login = NULL
                WHERE id = ?
                """,
                (user_id,),
            )

    def list_alerts(
        self, user_id: str, alert_status: str | None, repository_id: str | None
    ) -> list[SecurityAlert]:
        if alert_status is not None and alert_status not in _ALERT_STATUSES:
            raise unprocessable("status is invalid")
        with self._database.connect() as connection:
            seed_user_workspace(connection, user_id)
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
            seed_user_workspace(connection, user_id)
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
            seed_user_workspace(connection, user_id)
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
