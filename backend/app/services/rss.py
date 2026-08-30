import html
import socket
from urllib.parse import urljoin, urlparse

import bleach
import feedparser
import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.services.url_safety import (
    host_is_allowed,
    reject_private_resolved_addresses,
    require_global_response_peer,
    validate_url_shape,
)

ALLOWED_FEED_CONTENT_TYPES = {
    "application/atom+xml",
    "application/rss+xml",
    "application/xml",
    "text/xml",
}


def _host_is_allowed(hostname: str, allowed_hosts: set[str]) -> bool:
    return host_is_allowed(hostname, allowed_hosts)


def validate_feed_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = validate_url_shape(url, source_name="RSS")
    assert parsed.hostname is not None
    if not host_is_allowed(parsed.hostname, allowed_hosts):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="RSS host is not in the allowlist")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="RSS host cannot be resolved"
        ) from exc
    reject_private_resolved_addresses(addresses, source_name="RSS")
    return url


async def _download(settings: Settings, url: str) -> tuple[bytes, str]:
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
                require_global_response_peer(response, source_name="RSS")
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY, detail="RSS redirect is invalid"
                        )
                    current_url = validate_feed_url(urljoin(current_url, location), settings.rss_hosts)
                    continue
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"RSS source returned HTTP {response.status_code}",
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in ALLOWED_FEED_CONTENT_TYPES:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail=f"RSS content type is not allowed: {content_type or 'missing'}",
                    )
                content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
                if content_encoding not in {"", "identity"}:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="Compressed RSS responses are not allowed",
                    )
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > settings.max_response_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="RSS response exceeded the configured limit",
                        )
                    body.extend(chunk)
                return bytes(body), current_url
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail="RSS source redirected too many times"
    )


def _plain_text(value: str | None, limit: int) -> str:
    cleaned = bleach.clean(value or "", tags=[], attributes={}, strip=True)
    return html.unescape(cleaned).strip()[:limit]


def _safe_link(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.hostname else None


async def preview_feed(settings: Settings, url: str) -> dict:
    if not settings.rss_hosts:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="RSS fetching is disabled")
    body, final_url = await _download(settings, url)
    parsed = feedparser.parse(body, resolve_relative_uris=False, sanitize_html=True)
    if parsed.bozo and not parsed.entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="RSS feed could not be parsed"
        )

    items = []
    for entry in parsed.entries[:20]:
        link = _safe_link(entry.get("link"))
        title = _plain_text(entry.get("title"), 300)
        if not link or not title:
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "published": entry.get("published") or entry.get("updated"),
                "summary": _plain_text(entry.get("summary") or entry.get("description"), 500),
            }
        )
    return {
        "title": _plain_text(parsed.feed.get("title"), 300) or urlparse(final_url).hostname,
        "source_url": final_url,
        "items": items,
    }
