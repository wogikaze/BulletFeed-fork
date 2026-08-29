from pydantic import Field

from app.schemas.common import (
    ApiModel,
    Delta,
    FeedbackType,
    FeedItemStatus,
    Importance,
    Relation,
    SourceEvidence,
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
    sources: list[SourceEvidence] = Field(default_factory=list)
    additional_sources: list[SourceEvidence] = Field(default_factory=list)


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
    dwell_ms: int | None = Field(default=None, ge=0)
    visible_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    detail_opened: bool = False


class ExposuresRequest(ApiModel):
    items: list[ExposureItem] = Field(min_length=1, max_length=50)


class ExposuresResponse(ApiModel):
    accepted: int
