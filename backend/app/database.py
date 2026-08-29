import hmac
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.db.legacy_demo_cleanup import remove_legacy_demo_workspace
from app.db.migrations import apply_schema_migrations
from app.db.seed import TOPIC_CATALOG
from app.security import TokenCipher, token_hash


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _connect(self) -> sqlite3.Connection:
        return self.connect()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            apply_schema_migrations(connection)
            connection.executemany(
                "INSERT OR IGNORE INTO topic_catalog (id, name, type) VALUES (?, ?, ?)",
                TOPIC_CATALOG,
            )
            connection.execute(
                "UPDATE state_claims SET source_updated_at = valid_at WHERE source_updated_at = ''"
            )
            connection.execute(
                """
                UPDATE users
                SET onboarding_state = 'ready'
                WHERE onboarding_completed = 1 AND onboarding_state = 'profile'
                """
            )
            connection.execute(
                """
                UPDATE users
                SET github_credential_state = 'connected'
                WHERE github_connected = 1 AND github_credential_state = 'disconnected'
                """
            )
            remove_legacy_demo_workspace(connection)

    def create_oauth_flow(
        self,
        *,
        flow_id: str,
        user_id: str | None,
        state: str,
        poll_token: str,
        encrypted_verifier: str,
        expires_at: int,
    ) -> None:
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_flows (
                    flow_id, state_hash, poll_token_hash, pkce_verifier_encrypted,
                    user_id, status, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    flow_id,
                    token_hash(state),
                    token_hash(poll_token),
                    encrypted_verifier,
                    user_id,
                    expires_at,
                    now,
                ),
            )

    def claim_oauth_flow(self, state: str) -> sqlite3.Row | None:
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM oauth_flows
                WHERE state_hash = ? AND status = 'pending' AND expires_at > ?
                """,
                (token_hash(state), now),
            ).fetchone()
            if row is None:
                return None
            changed = connection.execute(
                "UPDATE oauth_flows SET status = 'exchanging' WHERE flow_id = ? AND status = 'pending'",
                (row["flow_id"],),
            ).rowcount
            return row if changed == 1 else None

    def fail_oauth_flow(self, flow_id: str, detail: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE oauth_flows SET status = 'failed', detail = ? WHERE flow_id = ?",
                (detail[:300], flow_id),
            )

    def issue_refreshable_session(
        self,
        *,
        user_id: str,
        access_token: str,
        refresh_token: str,
        access_expires_at: int,
        refresh_expires_at: int,
        revoke_existing_access: bool = False,
        revoke_existing_refresh: bool = False,
    ) -> None:
        now = int(time.time())
        with self._connect() as connection:
            if revoke_existing_access:
                connection.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            if revoke_existing_refresh:
                connection.execute(
                    "UPDATE user_refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (now, user_id),
                )
            connection.execute(
                """
                INSERT INTO user_sessions (token_hash, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash(access_token), user_id, access_expires_at, now),
            )
            connection.execute(
                """
                INSERT INTO user_refresh_tokens (
                    token_hash, user_id, expires_at, created_at, rotated_at, revoked_at
                ) VALUES (?, ?, ?, ?, NULL, NULL)
                """,
                (token_hash(refresh_token), user_id, refresh_expires_at, now),
            )

    def rotate_refresh_token(
        self,
        *,
        refresh_token: str,
        new_access_token: str,
        new_refresh_token: str,
        access_expires_at: int,
        refresh_expires_at: int,
    ) -> str | None:
        now = int(time.time())
        refresh_hash = token_hash(refresh_token)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT user_id
                FROM user_refresh_tokens
                WHERE token_hash = ? AND expires_at > ?
                  AND rotated_at IS NULL AND revoked_at IS NULL
                """,
                (refresh_hash, now),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            user_id = row["user_id"]
            changed = connection.execute(
                """
                UPDATE user_refresh_tokens
                SET rotated_at = ?
                WHERE token_hash = ? AND rotated_at IS NULL AND revoked_at IS NULL
                """,
                (now, refresh_hash),
            ).rowcount
            if changed != 1:
                connection.rollback()
                return None
            connection.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            connection.execute(
                """
                INSERT INTO user_sessions (token_hash, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash(new_access_token), user_id, access_expires_at, now),
            )
            connection.execute(
                """
                INSERT INTO user_refresh_tokens (
                    token_hash, user_id, expires_at, created_at, rotated_at, revoked_at
                ) VALUES (?, ?, ?, ?, NULL, NULL)
                """,
                (token_hash(new_refresh_token), user_id, refresh_expires_at, now),
            )
            connection.commit()
        return user_id

    def complete_oauth_flow(
        self,
        *,
        flow_id: str,
        user_id: str | None,
        github_user: dict[str, Any],
        encrypted_github_token: str,
        github_token_expires_at: int | None,
        app_access_token: str,
        encrypted_app_access_token: str,
        refresh_token: str,
        encrypted_refresh_token: str,
        app_session_expires_at: int,
        user_session_expires_at: int,
        refresh_expires_at: int,
    ) -> str:
        now = int(time.time())
        github_user_id = github_user["id"]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            linked = connection.execute(
                "SELECT id FROM users WHERE github_user_id = ? LIMIT 1",
                (github_user_id,),
            ).fetchone()
            canonical_user_id = linked["id"] if linked is not None else user_id
            if canonical_user_id is None:
                connection.rollback()
                raise ValueError("No existing BulletFeed account is linked to this GitHub identity")
            if user_id is not None and linked is not None and linked["id"] != user_id:
                if not self._ephemeral_user_is_empty(connection, user_id):
                    connection.rollback()
                    raise ValueError("GitHub identity is already linked to another BulletFeed account")
                self._delete_ephemeral_user(connection, user_id)
                canonical_user_id = linked["id"]

            connection.execute(
                """
                INSERT INTO github_connections (
                    github_user_id, login, avatar_url, github_token_encrypted,
                    token_expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(github_user_id) DO UPDATE SET
                    login = excluded.login,
                    avatar_url = excluded.avatar_url,
                    github_token_encrypted = excluded.github_token_encrypted,
                    token_expires_at = excluded.token_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    github_user_id,
                    github_user["login"],
                    github_user.get("avatar_url"),
                    encrypted_github_token,
                    github_token_expires_at,
                    now,
                ),
            )
            connection.execute("DELETE FROM app_sessions WHERE github_user_id = ?", (github_user_id,))
            connection.execute(
                """
                INSERT INTO app_sessions (token_hash, github_user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash(app_access_token), github_user_id, app_session_expires_at, now),
            )
            connection.execute("DELETE FROM user_sessions WHERE user_id = ?", (canonical_user_id,))
            connection.execute(
                "UPDATE user_refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, canonical_user_id),
            )
            connection.execute(
                """
                INSERT INTO user_sessions (token_hash, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash(app_access_token), canonical_user_id, user_session_expires_at, now),
            )
            connection.execute(
                """
                INSERT INTO user_refresh_tokens (
                    token_hash, user_id, expires_at, created_at, rotated_at, revoked_at
                ) VALUES (?, ?, ?, ?, NULL, NULL)
                """,
                (token_hash(refresh_token), canonical_user_id, refresh_expires_at, now),
            )
            connection.execute(
                """
                UPDATE users
                SET github_connected = 1,
                    github_credential_state = 'connected',
                    github_user_id = ?,
                    github_login = ?,
                    onboarding_state = CASE
                        WHEN onboarding_state = 'github_pending' THEN 'repository_pending'
                        ELSE onboarding_state
                    END
                WHERE id = ?
                """,
                (github_user_id, github_user["login"], canonical_user_id),
            )
            connection.execute(
                """
                UPDATE oauth_flows
                SET status = 'connected', github_login = ?, app_access_token_encrypted = ?,
                    refresh_token_encrypted = ?, user_id = ?, detail = NULL
                WHERE flow_id = ?
                """,
                (
                    github_user["login"],
                    encrypted_app_access_token,
                    encrypted_refresh_token,
                    canonical_user_id,
                    flow_id,
                ),
            )
            connection.commit()
        return canonical_user_id

    @staticmethod
    def _ephemeral_user_is_empty(connection: sqlite3.Connection, user_id: str) -> bool:
        user = connection.execute(
            "SELECT onboarding_completed FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user is None or bool(user["onboarding_completed"]):
            return False
        for table in (
            "topics",
            "feed_items",
            "feedback",
            "github_repo_watches",
            "security_alerts",
            "notifications",
            "event_follows",
        ):
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE user_id = ? LIMIT 1",  # nosec B608
                (user_id,),
            ).fetchone() is not None:
                return False
        profile = connection.execute(
            "SELECT occupation, interests_json, region FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return profile is None or (
            not profile["occupation"] and profile["interests_json"] == "[]" and not profile["region"]
        )

    @staticmethod
    def _delete_ephemeral_user(connection: sqlite3.Connection, user_id: str) -> None:
        connection.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM user_refresh_tokens WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def get_oauth_status(self, flow_id: str, poll_token: str, cipher: TokenCipher) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM oauth_flows WHERE flow_id = ?", (flow_id,)).fetchone()
        if row is None or not hmac.compare_digest(row["poll_token_hash"], token_hash(poll_token)):
            return None
        status = row["status"]
        if status == "exchanging":
            status = "pending"
        if row["expires_at"] <= int(time.time()) and status != "failed":
            status = "expired"
        access_token = None
        refresh_token = None
        if status == "connected" and row["app_access_token_encrypted"]:
            access_token = cipher.decrypt(row["app_access_token_encrypted"])
            if row["refresh_token_encrypted"]:
                refresh_token = cipher.decrypt(row["refresh_token_encrypted"])
        return {
            "status": status,
            "github_login": row["github_login"],
            "app_access_token": access_token,
            "refresh_token": refresh_token,
            "detail": row["detail"],
        }

    def get_session(self, app_access_token: str, cipher: TokenCipher) -> dict[str, Any] | None:
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT c.github_user_id, c.login, c.avatar_url, c.github_token_encrypted,
                       c.token_expires_at, s.expires_at AS session_expires_at
                FROM app_sessions s
                JOIN github_connections c ON c.github_user_id = s.github_user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash(app_access_token), now),
            ).fetchone()
        if row is None or (row["token_expires_at"] is not None and row["token_expires_at"] <= now):
            return None
        return {
            "github_user_id": row["github_user_id"],
            "login": row["login"],
            "avatar_url": row["avatar_url"],
            "github_token": cipher.decrypt(row["github_token_encrypted"]),
        }
