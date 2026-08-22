import hmac
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.security import TokenCipher, token_hash


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_flows (
                    flow_id TEXT PRIMARY KEY,
                    state_hash TEXT NOT NULL UNIQUE,
                    poll_token_hash TEXT NOT NULL,
                    pkce_verifier_encrypted TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT,
                    github_login TEXT,
                    app_access_token_encrypted TEXT,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS github_connections (
                    github_user_id INTEGER PRIMARY KEY,
                    login TEXT NOT NULL,
                    avatar_url TEXT,
                    github_token_encrypted TEXT NOT NULL,
                    token_expires_at INTEGER,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_sessions (
                    token_hash TEXT PRIMARY KEY,
                    github_user_id INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(github_user_id) REFERENCES github_connections(github_user_id)
                );
                """
            )

    def create_oauth_flow(
        self,
        *,
        flow_id: str,
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
                    status, expires_at, created_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (flow_id, token_hash(state), token_hash(poll_token), encrypted_verifier, expires_at, now),
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

    def complete_oauth_flow(
        self,
        *,
        flow_id: str,
        github_user: dict[str, Any],
        encrypted_github_token: str,
        github_token_expires_at: int | None,
        app_access_token: str,
        encrypted_app_access_token: str,
        session_expires_at: int,
    ) -> None:
        now = int(time.time())
        with self._connect() as connection:
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
                    github_user["id"],
                    github_user["login"],
                    github_user.get("avatar_url"),
                    encrypted_github_token,
                    github_token_expires_at,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO app_sessions (token_hash, github_user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash(app_access_token), github_user["id"], session_expires_at, now),
            )
            connection.execute(
                """
                UPDATE oauth_flows
                SET status = 'connected', github_login = ?, app_access_token_encrypted = ?, detail = NULL
                WHERE flow_id = ?
                """,
                (github_user["login"], encrypted_app_access_token, flow_id),
            )

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
        if status == "connected" and row["app_access_token_encrypted"]:
            access_token = cipher.decrypt(row["app_access_token_encrypted"])
        return {
            "status": status,
            "github_login": row["github_login"],
            "app_access_token": access_token,
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
