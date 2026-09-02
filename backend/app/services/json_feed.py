from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import urlparse

import bleach
import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.services.rss import require_global_response_peer, rewrite_http_redirect_to_https, validate_feed_url
from app.services.source_ingestion import NormalizedObservation
from app.services.timestamps import canonical_timestamp

_ALLOWED_CONTENT_TYPES = {"application/feed+json", "application/json"}


async def fetch_json_feed(settings: Settings, url: str) -> tuple[dict[str, Any], str]:
    if not settings.rss_hosts:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Feed fetching is disabled")
    current_url = validate_feed_url(url, settings.rss_hosts)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        for _ in range(4):
            async with client.stream(
                "GET",
                current_url,
                follow_redirects=False,
                headers={
                    "User-Agent": settings.crawler_user_agent,
                    "Accept-Encoding": "identity",
                },
            ) as response:
                require_global_response_peer(response, source_name="JSON Feed")
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="JSON Feed redirect is invalid",
                        )
                    current_url = validate_feed_url(
                        rewrite_http_redirect_to_https(current_url, location),
                        settings.rss_hosts,
                    )
                    continue
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"JSON Feed source returned HTTP {response.status_code}",
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in _ALLOWED_CONTENT_TYPES:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail=f"JSON Feed content type is not allowed: {content_type or 'missing'}",
                    )
                content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
                if content_encoding not in {"", "identity"}:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="Compressed JSON Feed responses are not allowed",
                    )
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > settings.max_response_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="JSON Feed response exceeded the configured limit",
                        )
                    body.extend(chunk)
                try:
                    data = json.loads(bytes(body))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="JSON Feed could not be parsed",
                    ) from exc
                if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="JSON Feed has invalid structure",
                    )
                return data, current_url
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="JSON Feed redirected too many times")


def normalize_json_feed(feed: dict[str, Any], *, feed_url: str) -> tuple[NormalizedObservation, ...]:
    source_key = _safe_url(feed.get("feed_url")) or feed_url
    observations: list[NormalizedObservation] = []
    items = feed.get("items")
    if not isinstance(items, list):
        return ()
    for item in items[:100]:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            continue
        canonical_url = _safe_url(item.get("url")) or _safe_url(item.get("external_url"))
        if canonical_url is None:
            continue
        published_at = canonical_timestamp(item.get("date_published")) or canonical_timestamp(
            item.get("date_modified")
        )
        payload = {
            "id": item_id,
            "url": canonical_url,
            "title": _text(item.get("title"), 500),
            "summary": _text(item.get("summary"), 4000),
            "content_text": _text(item.get("content_text"), 8000),
            "content_html": _text(item.get("content_html"), 8000),
            "date_published": _text(item.get("date_published"), 100),
            "date_modified": _text(item.get("date_modified"), 100),
        }
        observations.append(
            NormalizedObservation(
                source_type="json_feed",
                source_key=source_key,
                source_observation_id=item_id,
                payload=payload,
                original_url=canonical_url,
                published_at=published_at,
            )
        )
    return tuple(observations)


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = bleach.clean(value, tags=[], attributes={}, strip=True)
    return html.unescape(cleaned).strip()[:limit]


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.hostname else None
