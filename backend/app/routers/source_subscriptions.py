from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.config import Settings
from app.database import Database
from app.dependencies import get_database, get_settings, require_user
from app.schemas.source_subscriptions import (
    SourceSubscription,
    SourceSubscriptionCreate,
    SourceSubscriptionList,
    SourceSubscriptionPublisher,
    SourceSubscriptionState,
    SourceSubscriptionStatus,
    UserSourceKind,
)
from app.services.source_subscriptions import (
    UserSourceSubscription,
    add_user_source_subscription,
    iso_timestamp,
    list_user_source_subscriptions,
    remove_user_source_subscription,
)

router = APIRouter(prefix="/v1", tags=["source-subscriptions"])


def _public_subscription(item: UserSourceSubscription) -> SourceSubscription:
    publisher = None
    if item.publisher_slug and item.publisher_display_name:
        publisher = SourceSubscriptionPublisher(
            slug=item.publisher_slug,
            display_name=item.publisher_display_name,
        )
    if item.kind not in {"statuspage", "rss_atom", "json_feed"}:
        raise RuntimeError(f"unsupported user source kind: {item.kind}")
    if item.state not in {"pending", "ok", "failing"}:
        raise RuntimeError(f"unsupported subscription state: {item.state}")
    kind: UserSourceKind = item.kind
    state: SourceSubscriptionState = item.state
    return SourceSubscription(
        id=item.id,
        kind=kind,
        canonical_url=item.canonical_url,
        page_id=item.page_id,
        publisher=publisher,
        status=SourceSubscriptionStatus(
            selected=item.selected,
            state=state,
            last_success_at=iso_timestamp(item.last_success_at),
            last_attempt_at=iso_timestamp(item.last_attempt_at),
            failure_count=item.failure_count,
            next_run_at=iso_timestamp(item.next_run_at),
        ),
    )


@router.get("/me/sources", response_model=SourceSubscriptionList)
def list_my_sources(
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> SourceSubscriptionList:
    items = list_user_source_subscriptions(database, user_id=user["user_id"])
    return SourceSubscriptionList(items=[_public_subscription(item) for item in items])


@router.post("/me/sources", response_model=SourceSubscription)
def add_my_source(
    body: SourceSubscriptionCreate,
    response: Response,
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SourceSubscription:
    item = add_user_source_subscription(
        database,
        settings,
        user_id=user["user_id"],
        kind=body.kind,
        url=body.url,
        page_id=body.page_id,
        catch_up=body.catch_up,
    )
    response.status_code = status.HTTP_201_CREATED if item.created else status.HTTP_200_OK
    return _public_subscription(item)


@router.delete("/me/sources/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_source(
    subscription_id: str,
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> Response:
    remove_user_source_subscription(
        database,
        user_id=user["user_id"],
        subscription_id=subscription_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
