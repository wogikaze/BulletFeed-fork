from pydantic import Field

from app.schemas.common import (
    ApiModel,
    Delta,
    FeedbackType,
    FeedItemStatus,
    Importance,
    Relation,
)


class PublicFeedItem(ApiModel):
    id: str
    event_id: str
    delta: Delta
    title: str
    importance: Importance
    relation: Relation
    status: FeedItemStatus
    following: bool
    updated_at: str
    delivery_id: str


class FeedPage(ApiModel):
    items: list[PublicFeedItem]
    next_cursor: str | None = None


class FeedFeedbackRequest(ApiModel):
    type: FeedbackType


class FeedFeedbackResponse(ApiModel):
    feed_item_id: str
    type: FeedbackType
    status: FeedItemStatus


class ReadResponse(ApiModel):
    feed_item_id: str
    status: FeedItemStatus


class ExposureItem(ApiModel):
    delivery_id: str
    displayed_at: str


class ExposuresRequest(ApiModel):
    items: list[ExposureItem] = Field(min_length=1, max_length=50)


class ExposuresResponse(ApiModel):
    accepted: int
