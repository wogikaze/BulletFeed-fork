from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.config import Settings, get_settings
from app.database import Database
from app.dependencies import get_database, require_user
from app.errors import not_found, unprocessable
from app.schemas.source_discovery import (
    SiteFeedDiscoverItem,
    SiteFeedDiscoverRequest,
    SiteFeedDiscoverResult,
    SourceRecommendationDecisionRequest,
    SourceRecommendationItem,
    SourceRecommendationList,
)
from app.schemas.source_subscriptions import SourceSubscriptionPublisher
from app.services.abuse import request_client_key
from app.services.source_access_policy import SourceAccessPolicy
from app.services.source_discovery import (
    SourceCandidate,
    list_source_recommendations_for_user,
    record_source_recommendation_decision,
)
from app.services.source_feed_discover import SiteFeedCandidate, discover_feeds_from_site_url

router = APIRouter(prefix="/v1", tags=["source-discovery"])


def _public_item(item: SourceCandidate) -> SourceRecommendationItem:
    publisher = None
    if item.publisher_slug and item.publisher_display_name:
        publisher = SourceSubscriptionPublisher(
            slug=item.publisher_slug,
            display_name=item.publisher_display_name,
        )
    return SourceRecommendationItem(
        id=item.candidate_id,
        endpoint_id=item.endpoint_id,
        canonical_url=item.canonical_url,
        family=item.family,
        discovery_method=item.discovery_method,
        discovery_provenance=item.discovery_provenance,
        verification_status=item.verification_status,
        authority_status=item.authority_status,
        authority_confidence=item.authority_confidence,
        evidence_eligible=False,
        discovery_only=item.discovery_only,
        reason=item.match_reason,
        explanation=item.explanation,
        matched_concepts=list(item.matched_concept_ids),
        match_origin=item.match_origin,
        match_kind=item.match_kind,
        score=item.score,
        recommendation_status=item.recommendation_status,
        actionability=item.actionability,
        publisher=publisher,
    )


@router.get("/me/source-recommendations", response_model=SourceRecommendationList)
def list_my_source_recommendations(
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=40)] = 20,
    include_ignored: Annotated[bool, Query(alias="includeIgnored")] = False,
) -> SourceRecommendationList:
    result = list_source_recommendations_for_user(
        database,
        user["user_id"],
        include_ignored=include_ignored,
        limit=limit,
    )
    return SourceRecommendationList(
        version=result.version,
        items=[_public_item(item) for item in result.items],
        runtime_hint_count=result.runtime_hint_count,
        seed_fallback_used=result.seed_fallback_used,
    )


@router.post("/me/source-recommendations/{candidate_id}", response_model=SourceRecommendationItem)
def decide_source_recommendation(
    candidate_id: str,
    body: SourceRecommendationDecisionRequest,
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
) -> SourceRecommendationItem:
    try:
        item = record_source_recommendation_decision(
            database,
            user_id=user["user_id"],
            candidate_id=candidate_id,
            decision=body.decision,
        )
    except KeyError as exc:
        raise not_found("Source recommendation was not found") from exc
    except ValueError as exc:
        raise unprocessable(str(exc)) from exc
    return _public_item(item)


def _policy(database: Annotated[Database, Depends(get_database)]) -> SourceAccessPolicy:
    return SourceAccessPolicy(database)


def _public_feed_item(item: SiteFeedCandidate) -> SiteFeedDiscoverItem:
    publisher = None
    if item.publisher_slug and item.publisher_display_name:
        publisher = SourceSubscriptionPublisher(
            slug=item.publisher_slug,
            display_name=item.publisher_display_name,
        )
    return SiteFeedDiscoverItem(
        id=item.candidate_id,
        endpoint_id=item.endpoint_id,
        canonical_url=item.canonical_url,
        family=item.family,
        discovery_method=item.discovery_method,
        discovery_provenance=item.discovery_provenance,
        title=item.title,
        preferred=item.preferred,
        evidence_eligible=False,
        discovery_only=True,
        actionability=item.actionability,
        verification_status=item.verification_status,
        authority_status=item.authority_status,
        explanation=item.explanation,
        site_url=item.site_url,
        publisher=publisher,
    )


@router.post("/me/sources/discover", response_model=SiteFeedDiscoverResult)
async def discover_site_feeds(
    body: SiteFeedDiscoverRequest,
    request: Request,
    user: Annotated[dict, Depends(require_user)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
    policy: Annotated[SourceAccessPolicy, Depends(_policy)],
) -> SiteFeedDiscoverResult:
    cache_args = {"url": body.url.strip()}
    with policy.acquire(user["user_id"], client_key=request_client_key(request)):
        cached = policy.get_cached("site_feed_discover", cache_args)
        if cached is not None:
            return SiteFeedDiscoverResult.model_validate(cached)
        result = await discover_feeds_from_site_url(
            settings,
            body.url,
            database=database,
        )
        payload = SiteFeedDiscoverResult(
            version=result.version,
            site_url=result.site_url,
            canonical_site_url=result.canonical_site_url,
            preferred_family=result.preferred_family,
            items=[_public_feed_item(item) for item in result.items],
        )
        policy.put_cached(
            "site_feed_discover",
            cache_args,
            payload.model_dump(mode="json"),
        )
        return payload
