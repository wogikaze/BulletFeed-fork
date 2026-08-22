from __future__ import annotations

import base64

from fastapi import HTTPException

from app.config import Settings
from app.database import Database
from app.db.seed import DEMO_REPOSITORIES, seed_user_workspace
from app.errors import not_found, unprocessable
from app.schemas.integrations import (
    GithubConnection,
    GithubRepository,
    GithubRepositoryPage,
    GithubImportResult,
    NotificationItem,
    NotificationTarget,
    SecurityAlert,
    SecurityAlertPackage,
    SecurityAlertRepository,
)
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
    def __init__(self, database: Database) -> None:
        self._database = database
        self._me_store = MeStore(database)

    def github_connection(self, user_id: str, github_connected: bool) -> GithubConnection:
        with self._database.connect() as connection:
            watches = connection.execute(
                "SELECT COUNT(*) AS count FROM github_repo_watches WHERE user_id = ? AND selected = 1",
                (user_id,),
            ).fetchone()["count"]
            row = connection.execute(
                "SELECT login FROM github_connections WHERE github_user_id = ("
                "  SELECT github_user_id FROM app_sessions WHERE token_hash = ("
                "    SELECT token_hash FROM user_sessions WHERE user_id = ? LIMIT 1"
                "  ) LIMIT 1"
                ")",
                (user_id,),
            ).fetchone()
        login = row["login"] if row is not None and row["login"] else None
        return GithubConnection(connected=github_connected or watches > 0, account_login=login)

    def list_repositories(
        self, user_id: str, query: str | None, cursor: str | None, limit: int
    ) -> GithubRepositoryPage:
        if limit < 1 or limit > 50:
            raise unprocessable("limit must be 1-50")
        after = _decode_cursor(cursor) if cursor else ""
        with self._database.connect() as connection:
            selected = {
                row["repository_id"]
                for row in connection.execute(
                    "SELECT repository_id FROM github_repo_watches WHERE user_id = ? AND selected = 1",
                    (user_id,),
                )
            }
        items = []
        for repo in DEMO_REPOSITORIES:
            if query and query.lower() not in repo["full_name"].lower():
                continue
            if after and repo["id"] <= after:
                continue
            items.append(
                GithubRepository(
                    id=repo["id"],
                    full_name=repo["full_name"],
                    html_url=repo["html_url"],
                    private=repo["private"],
                    description=repo["description"],
                    language=repo["language"],
                    selected=repo["id"] in selected,
                    updated_at=repo["updated_at"],
                )
            )
        items.sort(key=lambda item: item.id)
        page = items[:limit]
        next_cursor = _encode_cursor(page[-1].id) if len(items) > limit else None
        return GithubRepositoryPage(items=page, next_cursor=next_cursor)

    def update_repositories(self, user_id: str, repository_ids: list[str]) -> GithubConnection:
        known = {repo["id"]: repo for repo in DEMO_REPOSITORIES}
        unknown = [repo_id for repo_id in repository_ids if repo_id not in known]
        if unknown:
            raise unprocessable("unknown repository id")
        with self._database.connect() as connection:
            connection.execute("DELETE FROM github_repo_watches WHERE user_id = ?", (user_id,))
            for repo_id in repository_ids:
                repo = known[repo_id]
                connection.execute(
                    """
                    INSERT INTO github_repo_watches (user_id, repository_id, full_name, html_url, selected)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (user_id, repo_id, repo["full_name"], repo["html_url"]),
                )
            connection.execute("UPDATE users SET github_connected = 1 WHERE id = ?", (user_id,))
            row = connection.execute(
                "SELECT login FROM github_connections WHERE github_user_id = ("
                "  SELECT github_user_id FROM app_sessions WHERE token_hash = ("
                "    SELECT token_hash FROM user_sessions WHERE user_id = ? LIMIT 1"
                "  ) LIMIT 1"
                ")",
                (user_id,),
            ).fetchone()
        login = row["login"] if row is not None and row["login"] else None
        return GithubConnection(connected=True, account_login=login)

    async def import_repository_keywords(
        self,
        user_id: str,
        full_name: str,
        settings: Settings,
        github_token: str | None = None,
    ) -> GithubImportResult:
        stripped = full_name.strip()
        parts = stripped.split("/")
        if len(parts) != 2 or not all(parts):
            raise unprocessable("full_name must be in owner/repo format")
        owner, repo = parts
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
            connection.execute("UPDATE users SET github_connected = 0 WHERE id = ?", (user_id,))

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
