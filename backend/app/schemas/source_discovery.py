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
    publisher: SourceSubscriptionPublisher | None = None


class SourceRecommendationList(ApiModel):
    version: str
    items: list[SourceRecommendationItem]
    runtime_hint_count: int = 0
    seed_fallback_used: bool = False


class SourceRecommendationDecisionRequest(ApiModel):
    decision: SourceRecommendationDecision = Field(min_length=1)
