from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.database import Database
from app.security import TokenCipher


def get_database(settings: Annotated[Settings, Depends(get_settings)]) -> Database:
    return Database(settings.database_path)


def get_cipher(settings: Annotated[Settings, Depends(get_settings)]) -> TokenCipher:
    try:
        return TokenCipher(settings.token_encryption_key.get_secret_value())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def require_session(
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is required")
    app_access_token = authorization.removeprefix("Bearer ").strip()
    session = database.get_session(app_access_token, cipher)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid or expired")
    return session
