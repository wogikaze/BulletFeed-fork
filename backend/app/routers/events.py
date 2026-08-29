from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.database import Database
from app.dependencies import get_database, require_user
from app.schemas.events import EventDetail, FollowingRequest, FollowingResponse
from app.stores.event_store import EventStore

router = APIRouter(prefix="/v1", tags=["events"])


def _store(database: Annotated[Database, Depends(get_database)]) -> EventStore:
    return EventStore(database)


@router.get("/events/{event_id}", response_model=EventDetail)
def get_event(
    event_id: str,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[EventStore, Depends(_store)],
    from_feed_item: Annotated[str | None, Query(alias="fromFeedItem")] = None,
) -> EventDetail:
    return store.get_event(user["user_id"], event_id, from_feed_item)


@router.put("/events/{event_id}/following", response_model=FollowingResponse)
def update_following(
    event_id: str,
    body: FollowingRequest,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[EventStore, Depends(_store)],
) -> FollowingResponse:
    return FollowingResponse.model_validate(
        store.set_following(
            user["user_id"],
            event_id,
            body.following,
            catch_up=body.catch_up,
        )
    )
