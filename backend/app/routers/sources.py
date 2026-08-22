import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.models import FeedPreview, OsvQuery, ReleaseItem, StatuspageSummary, VulnerabilityItem
from app.services import github, osv, rss, statuspage

router = APIRouter(prefix="/v1/sources", tags=["sources"])
GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


@router.get("/github/releases", response_model=list[ReleaseItem])
async def github_releases(
    owner: Annotated[str, Query(min_length=1, max_length=100)],
    repository: Annotated[str, Query(min_length=1, max_length=100)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[ReleaseItem]:
    if not GITHUB_NAME.fullmatch(owner) or not GITHUB_NAME.fullmatch(repository):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid repository name"
        )
    releases = await github.list_releases(settings, owner, repository)
    return [
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


@router.post("/osv/query", response_model=list[VulnerabilityItem])
async def osv_query(
    query: OsvQuery,
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[VulnerabilityItem]:
    vulnerabilities = await osv.query_vulnerabilities(
        settings,
        ecosystem=query.ecosystem,
        package=query.package,
        version=query.version,
    )
    return [
        VulnerabilityItem(id=item["id"], modified=item.get("modified"))
        for item in vulnerabilities
        if isinstance(item, dict) and item.get("id")
    ]


@router.get("/rss/preview", response_model=FeedPreview)
async def rss_preview(
    url: Annotated[str, Query(min_length=12, max_length=2_048)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FeedPreview:
    return FeedPreview(**(await rss.preview_feed(settings, url)))


@router.get("/statuspage/{page_id}", response_model=StatuspageSummary)
async def statuspage_summary(
    page_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> StatuspageSummary:
    data = await statuspage.get_summary(settings, page_id)
    page = data.get("page") or {}
    current_status = data.get("status") or {}
    return StatuspageSummary(
        page_name=str(page.get("name") or page_id),
        status=str(current_status.get("description") or "Unknown"),
        indicator=str(current_status.get("indicator") or "none"),
        unresolved_incidents=len(data.get("incidents") or []),
        scheduled_maintenances=len(data.get("scheduled_maintenances") or []),
    )
