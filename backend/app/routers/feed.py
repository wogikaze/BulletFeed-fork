from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.database import Database
from app.dependencies import get_database, require_user
from app.schemas.common import SourceEvidence
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


def _store(
    database: Annotated[Database, Depends(get_database)],
) -> FeedStore:
    return FeedStore(database)


def _event_sources(database: Database, event_id: str) -> list[SourceEvidence]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT publisher, kind, title, url, published_at, retrieved_at, evidence
            FROM event_sources
            WHERE event_id = ?
            ORDER BY published_at DESC, retrieved_at DESC, id DESC
            """,
            (event_id,),
        ).fetchall()
    return [
        SourceEvidence(
            publisher=row["publisher"],
            kind=row["kind"],
            title=row["title"],
            url=row["url"],
            published_at=row["published_at"],
            retrieved_at=row["retrieved_at"],
            evidence=row["evidence"],
        )
        for row in rows
    ]


@router.get("/feed", response_model=FeedPage)
def get_feed(
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
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
    for item in items:
        item.sources = _event_sources(database, item.event_id)
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
