import gzip
import html
import io
import socket
import zlib
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
_SNIFFABLE_CONTENT_TYPES = ALLOWED_FEED_CONTENT_TYPES | {
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "text/plain",
    "text/html",
    "application/xhtml+xml",
}
_XML_PREFIXES = (b"<?xml", b"<rss", b"<feed", b"<rdf")


def _host_is_allowed(hostname: str, allowed_hosts: set[str]) -> bool:
    return host_is_allowed(hostname, allowed_hosts)


def _looks_like_xml_feed(body: bytes) -> bool:
    head = body.lstrip()[:256]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:].lstrip()
    lowered = head[:80].lower()
    return any(lowered.startswith(prefix) for prefix in _XML_PREFIXES)


def _feed_byte_limit(settings: Settings) -> int:
    return int(settings.max_feed_response_bytes)


def validate_feed_url(
    url: str,
    allowed_hosts: set[str],
    *,
    enforce_allowlist: bool = True,
) -> str:
    parsed = validate_url_shape(url, source_name="RSS")
    if parsed.hostname is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RSS URL must be HTTPS and must not contain credentials",
        )
    from app.services.source_discovery_seeds import is_curated_subscribe_feed_url

    if (
        enforce_allowlist
        and not host_is_allowed(parsed.hostname, allowed_hosts)
        and not is_curated_subscribe_feed_url(url)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="RSS host is not in the allowlist")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="RSS host cannot be resolved"
        ) from exc
    reject_private_resolved_addresses(addresses, source_name="RSS")
    return url


def _bounded_decompress(body: bytes, encoding: str, *, limit: int) -> bytes:
    encoding = encoding.strip().lower()
    if encoding in {"", "identity"}:
        return body
    try:
        if encoding in {"gzip", "x-gzip"}:
            out = bytearray()
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as src:
                while True:
                    chunk = src.read(65_536)
                    if not chunk:
                        break
                    if len(out) + len(chunk) > limit:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="RSS response exceeded the configured limit",
                        )
                    out.extend(chunk)
            return bytes(out)
        if encoding == "deflate":
            decompressed = zlib.decompress(body)
            if len(decompressed) > limit:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="RSS response exceeded the configured limit",
                )
            return decompressed
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="RSS compressed payload could not be decoded",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Compressed RSS encoding is not allowed",
    )


def _accept_feed_body(content_type: str, body: bytes) -> None:
    if content_type in ALLOWED_FEED_CONTENT_TYPES:
        return
    if content_type in _SNIFFABLE_CONTENT_TYPES and _looks_like_xml_feed(body):
        return
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=f"RSS content type is not allowed: {content_type or 'missing'}",
    )


async def _download(settings: Settings, url: str) -> tuple[bytes, str]:
    current_url = validate_feed_url(url, settings.rss_hosts, enforce_allowlist=True)
    limit = _feed_byte_limit(settings)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        for _ in range(4):
            async with client.stream(
                "GET",
                current_url,
                follow_redirects=False,
                headers={
                    "User-Agent": settings.crawler_user_agent,
                    "Accept-Encoding": "identity",
                    "Accept": (
                        "application/rss+xml, application/atom+xml, "
                        "application/xml, text/xml;q=0.9, */*;q=0.1"
                    ),
                },
            ) as response:
                require_global_response_peer(response, source_name="RSS")
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY, detail="RSS redirect is invalid"
                        )
                    current_url = validate_feed_url(
                        urljoin(current_url, location),
                        settings.rss_hosts,
                        enforce_allowlist=False,
                    )
                    continue
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"RSS source returned HTTP {response.status_code}",
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > limit:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="RSS response exceeded the configured limit",
                        )
                    body.extend(chunk)
                decoded = _bounded_decompress(bytes(body), content_encoding, limit=limit)
                _accept_feed_body(content_type, decoded)
                return decoded, current_url
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


def _entry_feed_body(entry: object) -> str:
    content = getattr(entry, "content", None)
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            text = _plain_text(str(block.get("value") or ""), 20_000)
            if text:
                return text
    encoded = entry.get("content_encoded") if hasattr(entry, "get") else None
    if isinstance(encoded, str) and encoded.strip():
        return _plain_text(encoded, 20_000)
    return ""


async def preview_feed(settings: Settings, url: str) -> dict:
    from app.services.source_discovery_seeds import is_curated_subscribe_feed_url

    if not settings.rss_hosts and not is_curated_subscribe_feed_url(url):
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
        feed_body = _entry_feed_body(entry)
        items.append(
            {
                "title": title,
                "link": link,
                "published": entry.get("published") or entry.get("updated"),
                "summary": _plain_text(entry.get("summary") or entry.get("description"), 500),
                "content": feed_body,
            }
        )
    return {
        "title": _plain_text(parsed.feed.get("title"), 300) or urlparse(final_url).hostname,
        "source_url": final_url,
        "items": items,
    }
