import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.database import Database
from app.dependencies import get_database
from app.schemas.common import SessionRefreshRequest, SessionResponse
from app.services.abuse import request_client_key
from app.services.session_abuse_policy import SessionCreationPolicy

router = APIRouter(prefix="/v1", tags=["sessions"])

_ACCESS_TTL_SECONDS = 30 * 24 * 60 * 60
_REFRESH_TTL_SECONDS = 365 * 24 * 60 * 60


def _tokens(user_id: str) -> tuple[str, str, SessionResponse]:
    access_token = secrets.token_urlsafe(48)
    refresh_token = secrets.token_urlsafe(64)
    return (
        access_token,
        refresh_token,
        SessionResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user_id,
            access_expires_in_seconds=_ACCESS_TTL_SECONDS,
            refresh_expires_in_seconds=_REFRESH_TTL_SECONDS,
        ),
    )


@router.post("/sessions", response_model=SessionResponse)
def create_session(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
) -> SessionResponse:
    SessionCreationPolicy(database).consume(request_client_key(request))
    user_id = f"usr_{secrets.token_urlsafe(12)}"
    access_token, refresh_token, response = _tokens(user_id)
    now = int(time.time())
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, ?)", (user_id, now))
        connection.execute(
            """
            INSERT INTO profiles (user_id, occupation, interests_json, region, updated_at)
            VALUES (?, '', '[]', '', ?)
            """,
            (user_id, now),
        )
    database.issue_refreshable_session(
        user_id=user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=now + _ACCESS_TTL_SECONDS,
        refresh_expires_at=now + _REFRESH_TTL_SECONDS,
    )
    return response


@router.post("/sessions/refresh", response_model=SessionResponse)
def refresh_session(
    body: SessionRefreshRequest,
    database: Annotated[Database, Depends(get_database)],
) -> SessionResponse:
    access_token = secrets.token_urlsafe(48)
    refresh_token = secrets.token_urlsafe(64)
    now = int(time.time())
    user_id = database.rotate_refresh_token(
        refresh_token=body.refresh_token,
        new_access_token=access_token,
        new_refresh_token=refresh_token,
        access_expires_at=now + _ACCESS_TTL_SECONDS,
        refresh_expires_at=now + _REFRESH_TTL_SECONDS,
    )
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid, expired, or already rotated",
        )
    return SessionResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user_id,
        access_expires_in_seconds=_ACCESS_TTL_SECONDS,
        refresh_expires_in_seconds=_REFRESH_TTL_SECONDS,
    )
