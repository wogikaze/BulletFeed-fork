import asyncio
import re
from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.config import Settings, get_settings
from app.database import Database
from app.dependencies import get_database, require_user
from app.models import FeedPreview, OsvQuery, ReleaseItem, StatuspageSummary, VulnerabilityItem
from app.services import github, osv, rss, statuspage
from app.services.abuse import request_client_key
from app.services.source_access_policy import SourceAccessPolicy

router = APIRouter(prefix="/v1/sources", tags=["sources"])
GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _policy(database: Annotated[Database, Depends(get_database)]) -> SourceAccessPolicy:
    return SourceAccessPolicy(database)


async def _bounded[T](awaitable: Awaitable[T], settings: Settings) -> T:
    deadline = max(settings.request_timeout_seconds * 2, 1.0)
    try:
        async with asyncio.timeout(deadline):
            return await awaitable
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Source request exceeded total deadline",
        ) from exc


@router.get("/github/releases", response_model=list[ReleaseItem])
async def github_releases(
    request: Request,
    owner: Annotated[str, Query(min_length=1, max_length=100)],
    repository: Annotated[str, Query(min_length=1, max_length=100)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
    policy: Annotated[SourceAccessPolicy, Depends(_policy)],
) -> list[ReleaseItem]:
    if not GITHUB_NAME.fullmatch(owner) or not GITHUB_NAME.fullmatch(repository):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid repository name",
        )
    cache_args = {"owner": owner, "repository": repository}
    with policy.acquire(user["user_id"], client_key=request_client_key(request)):
        cached = policy.get_cached("github_releases", cache_args)
        if cached is not None:
            return [ReleaseItem.model_validate(item) for item in cached]
        releases = await _bounded(
            github.list_releases(settings, owner, repository),
            settings,
        )
        items = [
            ReleaseItem(
                id=item["id"],
                tag_name=item["tag_name"],
                name=item.get("name"),
                html_url=item["html_url"],
                published_at=item.get("published_at"),
                prerelease=bool(item.get("prerelease")),
                summary=(item.get("body") or "")[:500],
            )
            for item in releases
            if all(key in item for key in ("id", "tag_name", "html_url"))
        ]
        policy.put_cached(
            "github_releases",
            cache_args,
            [item.model_dump(mode="json") for item in items],
        )
        return items


@router.post("/osv/query", response_model=list[VulnerabilityItem])
async def osv_query(
    request: Request,
    query: OsvQuery,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
    policy: Annotated[SourceAccessPolicy, Depends(_policy)],
) -> list[VulnerabilityItem]:
    cache_args = query.model_dump(mode="json")
    with policy.acquire(user["user_id"], client_key=request_client_key(request)):
        cached = policy.get_cached("osv_query", cache_args)
        if cached is not None:
            return [VulnerabilityItem.model_validate(item) for item in cached]
        vulnerabilities = await _bounded(
            osv.query_vulnerabilities(
                settings,
                ecosystem=query.ecosystem,
                package=query.package,
                version=query.version,
            ),
            settings,
        )
        items = [
            VulnerabilityItem(id=item["id"], modified=item.get("modified"))
            for item in vulnerabilities
            if isinstance(item, dict) and item.get("id")
        ]
        policy.put_cached(
            "osv_query",
            cache_args,
            [item.model_dump(mode="json") for item in items],
        )
        return items


@router.get("/rss/preview", response_model=FeedPreview)
async def rss_preview(
    request: Request,
    url: Annotated[str, Query(min_length=12, max_length=2_048)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
    policy: Annotated[SourceAccessPolicy, Depends(_policy)],
) -> FeedPreview:
    cache_args = {"url": url}
    with policy.acquire(user["user_id"], client_key=request_client_key(request)):
        cached = policy.get_cached("rss_preview", cache_args)
        if cached is not None:
            return FeedPreview.model_validate(cached)
        item = FeedPreview(**(await _bounded(rss.preview_feed(settings, url), settings)))
        policy.put_cached("rss_preview", cache_args, item.model_dump(mode="json"))
        return item


@router.get("/statuspage/{page_id}", response_model=StatuspageSummary)
async def statuspage_summary(
    request: Request,
    page_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
    policy: Annotated[SourceAccessPolicy, Depends(_policy)],
) -> StatuspageSummary:
    cache_args = {"page_id": page_id}
    with policy.acquire(user["user_id"], client_key=request_client_key(request)):
        cached = policy.get_cached("statuspage_summary", cache_args)
        if cached is not None:
            return StatuspageSummary.model_validate(cached)
        data = await _bounded(statuspage.get_summary(settings, page_id), settings)
        page = data.get("page") or {}
        current_status = data.get("status") or {}
        item = StatuspageSummary(
            page_name=str(page.get("name") or page_id),
            status=str(current_status.get("description") or "Unknown"),
            indicator=str(current_status.get("indicator") or "none"),
            unresolved_incidents=len(data.get("incidents") or []),
            scheduled_maintenances=len(data.get("scheduled_maintenances") or []),
        )
        policy.put_cached("statuspage_summary", cache_args, item.model_dump(mode="json"))
        return item
