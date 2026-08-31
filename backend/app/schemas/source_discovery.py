from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.source_subscriptions import SourceSubscriptionPublisher

SourceRecommendationStatus = Literal["pending", "approved", "ignored"]
SourceMatchOrigin = Literal["explicit", "inferred"]
SourceMatchKind = Literal["direct", "neighbor"]
SourceRecommendationDecision = Literal["approved", "ignored"]


class SourceRecommendationItem(ApiModel):
    id: str
    endpoint_id: str
    canonical_url: str
    family: str
    discovery_method: str
    discovery_provenance: str
    verification_status: str
    authority_status: str
    authority_confidence: float
    evidence_eligible: bool
    discovery_only: bool
    reason: str
    explanation: str
    matched_concepts: list[str]
    match_origin: SourceMatchOrigin
    match_kind: SourceMatchKind
    score: float
    recommendation_status: SourceRecommendationStatus
    actionability: str
    publisher: SourceSubscriptionPublisher | None = None


class SourceRecommendationList(ApiModel):
    version: str
    items: list[SourceRecommendationItem]
    runtime_hint_count: int = 0
    seed_fallback_used: bool = False


class SourceRecommendationDecisionRequest(ApiModel):
    decision: SourceRecommendationDecision = Field(min_length=1)


class SiteFeedDiscoverRequest(ApiModel):
    url: str = Field(min_length=8, max_length=2_048)


class SiteFeedDiscoverItem(ApiModel):
    id: str
    endpoint_id: str
    canonical_url: str
    family: str
    discovery_method: str
    discovery_provenance: str
    title: str
    preferred: bool
    evidence_eligible: bool
    discovery_only: bool
    actionability: str
    verification_status: str
    authority_status: str
    explanation: str
    site_url: str
    publisher: SourceSubscriptionPublisher | None = None


class SiteFeedDiscoverResult(ApiModel):
    version: str
    site_url: str
    canonical_site_url: str
    preferred_family: str | None = None
    items: list[SiteFeedDiscoverItem]
