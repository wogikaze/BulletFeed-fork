from typing import Literal

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

DisplayMatchKind = Literal["direct", "adjacent", "inferred", "reference"]
DisplayDeltaKind = Literal[
    "new_fact",
    "additional",
    "state_update",
    "correction",
    "conflict",
    "duplicate",
]


class DisplayReason(ApiModel):
    """User-facing card explanation computed from the live ranker/projection inputs."""

    policy_version: str
    ranking_policy_version: str
    primary_code: str
    text: str
    codes: list[str] = Field(default_factory=list)
    match_kind: DisplayMatchKind
    delta_kind: DisplayDeltaKind
    independent_evidence_count: int = 1


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
    display_reason: DisplayReason | None = None


class FeedPage(ApiModel):
    items: list[PublicFeedItem]
    next_cursor: str | None = None


class FeedFeedbackRequest(ApiModel):
    type: FeedbackType


class FeedFeedbackResponse(ApiModel):
    feed_item_id: str
    type: FeedbackType
    status: FeedItemStatus


class RankingResetResponse(ApiModel):
    reset_at: int


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
