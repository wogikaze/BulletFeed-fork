from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.config import Settings, get_settings
from app.database import Database
from app.dependencies import get_database, require_user
from app.errors import not_found
from app.schemas.session_telemetry import FeedSessionResponse, SessionMetricsResponse
from app.services.session_telemetry import (
    POLICY_VERSION,
    end_feed_session,
    list_session_outcomes,
    reset_session_telemetry,
    start_feed_session,
    summarize_session_metrics,
    telemetry_enabled,
)

router = APIRouter(prefix="/v1", tags=["session-telemetry"])


@router.post(
    "/me/feed-sessions",
    response_model=FeedSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_feed_session(
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FeedSessionResponse:
    if not telemetry_enabled(settings):
        return FeedSessionResponse(version=POLICY_VERSION, id="", started_at=0, ended_at=None)
    with database.connect() as connection:
        session = start_feed_session(connection, user_id=user["user_id"], settings=settings)
        connection.commit()
    if session is None:
        return FeedSessionResponse(version=POLICY_VERSION, id="", started_at=0, ended_at=None)
    return FeedSessionResponse(
        version=POLICY_VERSION,
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
    )


@router.post("/me/feed-sessions/{session_id}/end", response_model=FeedSessionResponse)
def close_feed_session(
    session_id: str,
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FeedSessionResponse:
    with database.connect() as connection:
        session = end_feed_session(
            connection,
            user_id=user["user_id"],
            session_id=session_id,
            settings=settings,
        )
        connection.commit()
    if session is None:
        if not telemetry_enabled(settings):
            return FeedSessionResponse(version=POLICY_VERSION, id=session_id, started_at=0)
        raise not_found("Feed session was not found")
    return FeedSessionResponse(
        version=POLICY_VERSION,
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
    )


@router.get("/me/feed-sessions/metrics", response_model=SessionMetricsResponse)
def get_feed_session_metrics(
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> SessionMetricsResponse:
    with database.connect() as connection:
        metrics = summarize_session_metrics(list_session_outcomes(connection, user_id=user["user_id"]))
    return SessionMetricsResponse(
        version=metrics.version,
        session_count=metrics.session_count,
        displayed_count=metrics.displayed_count,
        useful_card_rate=metrics.useful_card_rate,
        already_known_reshow_rate=metrics.already_known_reshow_rate,
        cards_to_useful_item=metrics.cards_to_useful_item,
        feedback_response_rate=metrics.feedback_response_rate,
    )


@router.delete("/me/feed-sessions", status_code=status.HTTP_204_NO_CONTENT)
def delete_feed_sessions(
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> Response:
    with database.connect() as connection:
        reset_session_telemetry(connection, user_id=user["user_id"])
        connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
