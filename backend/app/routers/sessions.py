import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends

from app.database import Database
from app.db.seed import seed_user_workspace
from app.dependencies import get_database
from app.schemas.common import SessionResponse
from app.security import token_hash

router = APIRouter(prefix="/v1", tags=["sessions"])

_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


@router.post("/sessions", response_model=SessionResponse)
def create_session(database: Annotated[Database, Depends(get_database)]) -> SessionResponse:
    user_id = f"usr_{secrets.token_urlsafe(12)}"
    access_token = secrets.token_urlsafe(48)
    now = int(time.time())
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, ?)", (user_id, now))
        connection.execute(
            """
            INSERT INTO user_sessions (token_hash, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token_hash(access_token), user_id, now + _SESSION_TTL_SECONDS, now),
        )
        connection.execute(
            """
            INSERT INTO profiles (user_id, occupation, interests_json, region, updated_at)
            VALUES (?, '', '[]', '', ?)
            """,
            (user_id, now),
        )
        seed_user_workspace(connection, user_id)
    return SessionResponse(access_token=access_token, user_id=user_id)
