from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.database import Database
from app.dependencies import get_database, require_user
from app.schemas.events import EventDetail, EventSearchPage, FollowingRequest, FollowingResponse
from app.stores.event_search_store import EventSearchStore
from app.stores.event_store import EventStore

router = APIRouter(prefix="/v1", tags=["events"])


def _store(database: Annotated[Database, Depends(get_database)]) -> EventStore:
    return EventStore(database)


def _search_store(database: Annotated[Database, Depends(get_database)]) -> EventSearchStore:
    return EventSearchStore(database)


@router.get("/events/search", response_model=EventSearchPage)
def search_events(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[EventSearchStore, Depends(_search_store)],
    q: Annotated[str, Query(max_length=100)] = "",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> EventSearchPage:
    items, next_cursor = store.search(
        user["user_id"],
        query=q,
        cursor=cursor,
        limit=limit,
    )
    return EventSearchPage(items=items, next_cursor=next_cursor)


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
