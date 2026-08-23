from __future__ import annotations

import time

from fastapi import HTTPException, status

from app.database import Database
from app.security import token_hash

MAX_ACTIVE_FLOWS_PER_USER = 3
MAX_ACTIVE_RECOVERY_FLOWS = 20
TERMINAL_FLOW_RETENTION_SECONDS = 3600


def create_user_oauth_flow(
    database: Database,
    *,
    flow_id: str,
    user_id: str | None,
    state: str,
    poll_token: str,
    encrypted_verifier: str,
    expires_at: int,
    purpose: str = "user_link",
    now: int | None = None,
) -> None:
    """Create a bounded OAuth flow.

    Normal authorization is user-bound. A null user_id is valid only for an
    explicitly tagged account-recovery flow; legacy/unbound rows remain fail-closed.
    The existing detail column carries the pending flow purpose and is cleared on
    terminal completion, so no schema migration is required for this discriminator.
    """
    if purpose not in {"user_link", "account_recovery"}:
        raise ValueError("OAuth flow purpose is invalid")
    if user_id is None and purpose != "account_recovery":
        raise ValueError("Unbound OAuth flows must be account recovery flows")
    if user_id is not None and purpose != "user_link":
        raise ValueError("Account recovery flows must not be user-bound")

    current = int(time.time()) if now is None else now
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            DELETE FROM oauth_flows
            WHERE expires_at <= ?
               OR (status IN ('connected', 'failed') AND created_at < ?)
            """,
            (current, current - TERMINAL_FLOW_RETENTION_SECONDS),
        )
        if user_id is None:
            active = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM oauth_flows
                WHERE user_id IS NULL
                  AND detail = 'account_recovery'
                  AND status IN ('pending', 'exchanging')
                  AND expires_at > ?
                """,
                (current,),
            ).fetchone()["count"]
            limit = MAX_ACTIVE_RECOVERY_FLOWS
        else:
            active = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM oauth_flows
                WHERE user_id = ?
                  AND status IN ('pending', 'exchanging')
                  AND expires_at > ?
                """,
                (user_id, current),
            ).fetchone()["count"]
            limit = MAX_ACTIVE_FLOWS_PER_USER
        if active >= limit:
            connection.rollback()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many active GitHub authorization flows",
            )
        connection.execute(
            """
            INSERT INTO oauth_flows (
                flow_id, state_hash, poll_token_hash, pkce_verifier_encrypted,
                user_id, status, detail, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                flow_id,
                token_hash(state),
                token_hash(poll_token),
                encrypted_verifier,
                user_id,
                purpose,
                expires_at,
                current,
            ),
        )
        connection.commit()
