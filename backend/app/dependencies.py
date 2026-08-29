import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.database import Database
from app.security import TokenCipher, token_hash


def get_database(settings: Annotated[Settings, Depends(get_settings)]) -> Database:
    return Database(settings.database_path)


def get_cipher(settings: Annotated[Settings, Depends(get_settings)]) -> TokenCipher:
    try:
        return TokenCipher(settings.token_encryption_key.get_secret_value())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def require_user(
    database: Annotated[Database, Depends(get_database)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is required")
    access_token = authorization.removeprefix("Bearer ").strip()
    now = int(time.time())
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT u.id AS user_id, u.onboarding_completed, u.github_connected
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (token_hash(access_token), now),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid or expired")
    return {
        "user_id": row["user_id"],
        "onboarding_completed": bool(row["onboarding_completed"]),
        "github_connected": bool(row["github_connected"]),
    }
