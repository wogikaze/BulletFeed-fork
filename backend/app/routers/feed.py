from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.database import Database
from app.dependencies import get_database, require_user
from app.schemas.feed import (
    ExposuresRequest,
    ExposuresResponse,
    FeedFeedbackRequest,
    FeedFeedbackResponse,
    FeedPage,
    ReadResponse,
)
from app.stores.feed_store import FeedStore

router = APIRouter(prefix="/v1", tags=["feed"])


def _store(database: Annotated[Database, Depends(get_database)]) -> FeedStore:
    return FeedStore(database)


@router.get("/feed", response_model=FeedPage)
def get_feed(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[FeedStore, Depends(_store)],
    relation: Literal["direct", "adjacent", "reference"] | None = None,
    item_status: Annotated[
        Literal["unread", "read"] | None,
        Query(alias="status"),
    ] = None,
    cursor: str | None = None,
    limit: int = 20,
) -> FeedPage:
    items, next_cursor = store.list_feed(
        user["user_id"],
        relation=relation,
        item_status=item_status,
        cursor=cursor,
        limit=limit,
    )
    return FeedPage(items=items, next_cursor=next_cursor)


@router.put("/feed/items/{feed_item_id}/read", response_model=ReadResponse)
def mark_feed_item_read(
    feed_item_id: str,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[FeedStore, Depends(_store)],
) -> ReadResponse:
    return ReadResponse.model_validate(store.mark_read(user["user_id"], feed_item_id))


@router.post("/feed/items/{feed_item_id}/feedback", response_model=FeedFeedbackResponse)
def submit_feed_feedback(
    feed_item_id: str,
    body: FeedFeedbackRequest,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[FeedStore, Depends(_store)],
) -> FeedFeedbackResponse:
    return FeedFeedbackResponse.model_validate(store.save_feedback(user["user_id"], feed_item_id, body.type))


@router.post("/feed/exposures", response_model=ExposuresResponse)
def record_exposures(
    body: ExposuresRequest,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[FeedStore, Depends(_store)],
) -> ExposuresResponse:
    accepted = store.record_exposures(
        user["user_id"],
        [item.model_dump() for item in body.items],
    )
    return ExposuresResponse(accepted=accepted)
