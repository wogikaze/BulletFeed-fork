"""Discover RSS/Atom/JSON Feed candidates from a site or blog URL.

Discovery is not evidence. This path never writes Observations, Claims, or
subscriptions. A URL existing is not an event. Feeds are preferred over
generic web watch so the same publisher is not fetched twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.database import Database
from app.services.rss import ALLOWED_FEED_CONTENT_TYPES, require_global_response_peer, validate_feed_url
from app.services.source_actionability import resolve_source_actionability
from app.services.source_catalog import SourceKind, get_source_policy
from app.services.source_discovery import infer_source_family
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_registry import (
    AuthorityStatus,
    Endpoint,
    SourceRegistry,
    VerificationStatus,
    canonicalize_url,
    endpoint_id,
    publisher_id,
)
from app.services.web_snapshots import evaluate_robots, fetch_html_page

SITE_FEED_DISCOVER_VERSION = "site-feed-discover-v1"
DiscoveryMethodName = Literal[
    "html_link_alternate",
    "well_known_path",
    "direct_feed_url",
    "site_url_fallback",
]

_MAX_HTML_CHARS = 1_000_000
_MAX_CANDIDATES = 8
_MAX_WELL_KNOWN_PROBES = 5
_WELL_KNOWN_PATHS = ("/feed", "/rss", "/atom.xml", "/feed.xml", "/index.xml")
_JSON_FEED_TYPES = frozenset({"application/feed+json", "application/json"})
_JSON_FEED_MARKERS = (b"https://jsonfeed.org/version/", b"http://jsonfeed.org/version/")


@dataclass(frozen=True)
class AlternateFeedLink:
    href: str
    mime_type: str
    title: str
    family: SourceKind


@dataclass(frozen=True)
class SiteFeedCandidate:
    candidate_id: str
    endpoint_id: str
    canonical_url: str
    family: str
    discovery_method: DiscoveryMethodName
    discovery_provenance: str
    title: str
    preferred: bool
    evidence_eligible: bool
    discovery_only: bool
    actionability: str
    verification_status: str
    authority_status: str
    publisher_slug: str
    publisher_display_name: str
    site_url: str
    explanation: str


@dataclass(frozen=True)
class SiteFeedDiscoverResult:
    version: str
    site_url: str
    canonical_site_url: str
    preferred_family: str | None
    items: tuple[SiteFeedCandidate, ...]


def extract_alternate_feed_links(html_text: str, *, page_url: str) -> tuple[AlternateFeedLink, ...]:
    """Extract RSS/Atom/JSON Feed candidates from ``link rel=alternate``."""
    if len(html_text) > _MAX_HTML_CHARS:
        html_text = html_text[:_MAX_HTML_CHARS]
    parser = _AlternateFeedParser()
    parser.feed(html_text)
    found: list[AlternateFeedLink] = []
    seen: set[str] = set()
    for href, mime_type, title in parser.links:
        absolute = _absolute_http_url(href, page_url)
        if absolute is None:
            continue
        family = _family_from_alternate(mime_type, absolute)
        if family is None:
            continue
        try:
            canonical = canonicalize_url(absolute)
        except ValueError:
            continue
        key = f"{family.value}|{canonical}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            AlternateFeedLink(
                href=absolute,
                mime_type=mime_type,
                title=title,
                family=family,
            )
        )
    return tuple(found)


def well_known_feed_urls(site_url: str, *, limit: int = _MAX_WELL_KNOWN_PROBES) -> tuple[str, ...]:
    """Same-origin well-known feed paths, capped and conservative."""
    try:
        origin = _site_origin(site_url)
    except ValueError:
        return ()
    capped = max(1, min(int(limit), _MAX_WELL_KNOWN_PROBES))
    urls: list[str] = []
    seen: set[str] = set()
    for path in _WELL_KNOWN_PATHS[:capped]:
        candidate = urljoin(origin, path)
        try:
            if not _same_origin(origin, candidate):
                continue
            canonical = canonicalize_url(candidate)
        except ValueError:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        urls.append(candidate)
    return tuple(urls)


async def discover_feeds_from_site_url(
    settings: Settings,
    url: str,
    *,
    database: Database | None = None,
    registry: SourceRegistry | None = None,
    persist_registry: bool = True,
    probe_well_known: bool = True,
) -> SiteFeedDiscoverResult:
    """Fetch a site URL and return subscription candidates.

    Never creates subscriptions, Observations, or Claims.
    """
    hosts = _discovery_hosts(settings)
    if not hosts:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Web fetching is disabled")
    raw = url.strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="url is required",
        )
    source_registry = registry or SourceRegistry(database)
    validated = _validate_discovery_url(raw, hosts)
    pasted_family = infer_source_family(validated)
    if pasted_family in {SourceKind.RSS_ATOM, SourceKind.JSON_FEED}:
        robots = await evaluate_robots(settings, validated, allowed_hosts=hosts)
        if not robots.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Web fetch is disallowed by robots/crawl policy",
            )
        confirmed = await _confirm_feed_url(
            settings,
            validated,
            family=pasted_family,
            hosts=hosts,
        )
        if confirmed is not None:
            final_url, family = confirmed
            items = (
                _candidate_from_feed(
                    source_registry,
                    site_url=validated,
                    feed_url=final_url,
                    family=family,
                    method="direct_feed_url",
                    title="",
                    persist_registry=persist_registry,
                ),
            )
            return SiteFeedDiscoverResult(
                version=SITE_FEED_DISCOVER_VERSION,
                site_url=validated,
                canonical_site_url=canonicalize_url(final_url),
                preferred_family=family.value,
                items=items,
            )

    body, final_site_url, _robots = await fetch_html_page(
        settings,
        validated,
        allowed_hosts=hosts,
    )
    if canonicalize_url(validated) != final_site_url:
        _record_site_redirect(source_registry, validated, final_site_url, persist_registry)
    html_text = body.decode("utf-8", errors="replace")
    alternates = extract_alternate_feed_links(html_text, page_url=final_site_url)
    feed_items = _candidates_from_alternates(
        settings,
        source_registry,
        site_url=final_site_url,
        links=alternates,
        persist_registry=persist_registry,
    )
    if not feed_items and probe_well_known:
        feed_items = await _probe_well_known_feeds(
            settings,
            source_registry,
            site_url=final_site_url,
            hosts=hosts,
            persist_registry=persist_registry,
        )
    if feed_items:
        preferred = _preferred_feed_family(feed_items)
        ranked = tuple(item for item in feed_items if item.family != SourceKind.GENERIC_WEB.value)
        return SiteFeedDiscoverResult(
            version=SITE_FEED_DISCOVER_VERSION,
            site_url=validated,
            canonical_site_url=final_site_url,
            preferred_family=preferred,
            items=ranked[:_MAX_CANDIDATES],
        )
    fallback = _candidate_from_site(
        source_registry,
        site_url=final_site_url,
        persist_registry=persist_registry,
    )
    return SiteFeedDiscoverResult(
        version=SITE_FEED_DISCOVER_VERSION,
        site_url=validated,
        canonical_site_url=final_site_url,
        preferred_family=SourceKind.GENERIC_WEB.value,
        items=(fallback,),
    )


def _discovery_hosts(settings: Settings) -> set[str]:
    return set(settings.web_hosts) | set(settings.rss_hosts)


def _validate_discovery_url(url: str, hosts: set[str]) -> str:
    from app.services.web_snapshots import validate_web_url

    return validate_web_url(url, hosts)


def _family_from_alternate(mime_type: str, href: str) -> SourceKind | None:
    if mime_type in {"application/rss+xml", "application/atom+xml"}:
        return SourceKind.RSS_ATOM
    if mime_type == "application/feed+json":
        return SourceKind.JSON_FEED
    if mime_type == "application/json":
        path = urlparse(href).path.lower()
        if "feed" in path:
            return SourceKind.JSON_FEED
        return None
    if mime_type in {"application/xml", "text/xml"}:
        path = urlparse(href).path.lower()
        if any(token in path for token in ("feed", "rss", "atom")):
            return SourceKind.RSS_ATOM
        return None
    inferred = infer_source_family(href)
    if inferred in {SourceKind.RSS_ATOM, SourceKind.JSON_FEED}:
        return inferred
    return None


def _candidates_from_alternates(
    settings: Settings,
    registry: SourceRegistry,
    *,
    site_url: str,
    links: tuple[AlternateFeedLink, ...],
    persist_registry: bool,
) -> tuple[SiteFeedCandidate, ...]:
    items: list[SiteFeedCandidate] = []
    seen: set[str] = set()
    hosts = _discovery_hosts(settings)
    for link in links:
        try:
            validated = _validate_feed_candidate(link.href, hosts)
        except HTTPException:
            continue
        candidate = _candidate_from_feed(
            registry,
            site_url=site_url,
            feed_url=validated,
            family=link.family,
            method="html_link_alternate",
            title=link.title,
            persist_registry=persist_registry,
        )
        if candidate.candidate_id in seen:
            continue
        seen.add(candidate.candidate_id)
        items.append(candidate)
    return tuple(items)


async def _probe_well_known_feeds(
    settings: Settings,
    registry: SourceRegistry,
    *,
    site_url: str,
    hosts: set[str],
    persist_registry: bool,
) -> tuple[SiteFeedCandidate, ...]:
    items: list[SiteFeedCandidate] = []
    seen: set[str] = set()
    for probe_url in well_known_feed_urls(site_url):
        try:
            validated = _validate_feed_candidate(probe_url, hosts)
        except HTTPException:
            continue
        robots = await evaluate_robots(settings, validated, allowed_hosts=hosts)
        if not robots.allowed:
            continue
        confirmed = await _confirm_feed_url(
            settings,
            validated,
            family=infer_source_family(validated),
            hosts=hosts,
        )
        if confirmed is None:
            continue
        final_url, family = confirmed
        if family not in {SourceKind.RSS_ATOM, SourceKind.JSON_FEED}:
            continue
        if canonicalize_url(validated) != canonicalize_url(final_url) and persist_registry:
            try:
                registry.record_redirect(
                    previous_url=validated,
                    current_url=final_url,
                    family=family,
                    reason="feed_redirect",
                )
            except ValueError:
                pass
        candidate = _candidate_from_feed(
            registry,
            site_url=site_url,
            feed_url=final_url,
            family=family,
            method="well_known_path",
            title="",
            persist_registry=persist_registry,
        )
        if candidate.candidate_id in seen:
            continue
        seen.add(candidate.candidate_id)
        items.append(candidate)
    return tuple(items)


def _validate_feed_candidate(url: str, hosts: set[str]) -> str:
    return validate_feed_url(url, hosts)


async def _confirm_feed_url(
    settings: Settings,
    url: str,
    *,
    family: SourceKind,
    hosts: set[str],
) -> tuple[str, SourceKind] | None:
    try:
        current = validate_feed_url(url, hosts)
    except HTTPException:
        return None
    try:
        body, final_url, content_type = await _download_feed_probe(settings, current, hosts=hosts)
    except HTTPException:
        return None
    sniffed = _sniff_feed_family(content_type, body, family)
    if sniffed is None:
        return None
    return final_url, sniffed


async def _download_feed_probe(
    settings: Settings,
    url: str,
    *,
    hosts: set[str],
) -> tuple[bytes, str, str]:
    current_url = validate_feed_url(url, hosts)
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
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
                            "application/feed+json, application/json, "
                            "application/xml, text/xml;q=0.9, */*;q=0.1"
                        ),
                    },
                ) as response:
                    require_global_response_peer(response, source_name="Feed")
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(
                                status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="Feed redirect is invalid",
                            )
                        current_url = validate_feed_url(urljoin(current_url, location), hosts)
                        continue
                    if response.status_code >= 400:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Feed source returned HTTP {response.status_code}",
                        )
                    encoding = response.headers.get("content-encoding", "identity").strip().lower()
                    if encoding not in {"", "identity"}:
                        raise HTTPException(
                            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Compressed feed responses are not allowed",
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > settings.max_response_bytes:
                            raise HTTPException(
                                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail="Feed response exceeded the configured limit",
                            )
                        body.extend(chunk)
                    return bytes(body), canonicalize_url(current_url), content_type
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Feed source request timed out",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Feed source redirected too many times",
    )


def _sniff_feed_family(
    content_type: str,
    body: bytes,
    hinted: SourceKind,
) -> SourceKind | None:
    if content_type in _JSON_FEED_TYPES or any(marker in body for marker in _JSON_FEED_MARKERS):
        if hinted == SourceKind.JSON_FEED or b"jsonfeed.org" in body or content_type in _JSON_FEED_TYPES:
            if content_type in {"text/html", "application/xhtml+xml"}:
                return None
            return SourceKind.JSON_FEED
    if content_type in ALLOWED_FEED_CONTENT_TYPES:
        lowered = body[:400].lstrip().lower()
        if lowered.startswith(b"<html") or b"<html" in lowered[:80]:
            return None
        return SourceKind.RSS_ATOM
    lowered = body[:800].lstrip().lower()
    if lowered.startswith((b"<rss", b"<feed", b"<?xml")) and (b"<rss" in lowered or b"<feed" in lowered):
        return SourceKind.RSS_ATOM
    return None


def _candidate_from_feed(
    registry: SourceRegistry,
    *,
    site_url: str,
    feed_url: str,
    family: SourceKind,
    method: DiscoveryMethodName,
    title: str,
    persist_registry: bool,
) -> SiteFeedCandidate:
    publisher_slug = _publisher_slug(site_url)
    publisher_name = publisher_slug
    endpoint = _register_or_reuse(
        registry,
        url=feed_url,
        family=family,
        publisher_slug=publisher_slug,
        homepage_url=site_url,
        persist_registry=persist_registry,
    )
    publisher = registry.get_publisher(endpoint.publisher_id)
    if publisher is not None:
        publisher_slug = publisher.slug
        publisher_name = publisher.display_name
    display = title.strip() or endpoint.canonical_url
    explanation = (
        f"{display}. Discovered via {method.replace('_', ' ')}. "
        "Discovery is not evidence; subscribe to activate this feed. "
        "Feed subscription is preferred over generic web watch."
    )
    return SiteFeedCandidate(
        candidate_id=endpoint.endpoint_id,
        endpoint_id=endpoint.endpoint_id,
        canonical_url=endpoint.canonical_url,
        family=family.value,
        discovery_method=method,
        discovery_provenance=DiscoveryProvenance.WEBSITE_FEED.value,
        title=display,
        preferred=True,
        evidence_eligible=False,
        discovery_only=True,
        actionability=resolve_source_actionability(
            family=family.value,
            discovery_provenance=DiscoveryProvenance.WEBSITE_FEED.value,
            discovery_only=True,
        ),
        verification_status=VerificationStatus.UNVERIFIED.value,
        authority_status=AuthorityStatus.UNKNOWN.value,
        publisher_slug=publisher_slug,
        publisher_display_name=publisher_name,
        site_url=canonicalize_url(site_url),
        explanation=explanation,
    )


def _candidate_from_site(
    registry: SourceRegistry,
    *,
    site_url: str,
    persist_registry: bool,
) -> SiteFeedCandidate:
    publisher_slug = _publisher_slug(site_url)
    endpoint = _register_or_reuse(
        registry,
        url=site_url,
        family=SourceKind.GENERIC_WEB,
        publisher_slug=publisher_slug,
        homepage_url=site_url,
        persist_registry=persist_registry,
    )
    publisher = registry.get_publisher(endpoint.publisher_id)
    publisher_name = publisher.display_name if publisher is not None else publisher_slug
    if publisher is not None:
        publisher_slug = publisher.slug
    explanation = (
        "No RSS/Atom/JSON Feed was found. "
        "Generic web watch is offered as a safe fallback. "
        "Discovery is not evidence and does not create a subscription."
    )
    return SiteFeedCandidate(
        candidate_id=endpoint.endpoint_id,
        endpoint_id=endpoint.endpoint_id,
        canonical_url=endpoint.canonical_url,
        family=SourceKind.GENERIC_WEB.value,
        discovery_method="site_url_fallback",
        discovery_provenance=DiscoveryProvenance.WEBSITE_FEED.value,
        title=endpoint.canonical_url,
        preferred=True,
        evidence_eligible=False,
        discovery_only=True,
        actionability=resolve_source_actionability(
            family=SourceKind.GENERIC_WEB.value,
            discovery_provenance=DiscoveryProvenance.WEBSITE_FEED.value,
            discovery_only=True,
        ),
        verification_status=VerificationStatus.UNVERIFIED.value,
        authority_status=AuthorityStatus.UNKNOWN.value,
        publisher_slug=publisher_slug,
        publisher_display_name=publisher_name,
        site_url=canonicalize_url(site_url),
        explanation=explanation,
    )


def _register_or_reuse(
    registry: SourceRegistry,
    *,
    url: str,
    family: SourceKind,
    publisher_slug: str,
    homepage_url: str,
    persist_registry: bool,
) -> Endpoint:
    existing = registry.find_duplicate_endpoint(url, family=family)
    if existing is not None:
        return existing
    if persist_registry:
        registry.register_publisher(
            slug=publisher_slug,
            display_name=publisher_slug,
            homepage_url=homepage_url,
        )
        return registry.register_endpoint(
            url=url,
            family=family,
            publisher_slug=publisher_slug,
            verification_status=VerificationStatus.UNVERIFIED,
            authority_status=AuthorityStatus.UNKNOWN,
        )
    try:
        method = get_source_policy(family).discovery_method.value
    except ValueError:
        method = "html"
    return Endpoint(
        endpoint_id=endpoint_id(url=url, family=family),
        publisher_id=publisher_id(slug=publisher_slug, homepage_url=homepage_url),
        family=family.value,
        canonical_url=canonicalize_url(url),
        registered_url=url.strip(),
        discovery_method=method,
        verification_status=VerificationStatus.UNVERIFIED.value,
        authority_status=AuthorityStatus.UNKNOWN.value,
        created_at="1970-01-01T00:00:00Z",
    )


def _record_site_redirect(
    registry: SourceRegistry,
    previous_url: str,
    current_url: str,
    persist_registry: bool,
) -> None:
    if not persist_registry:
        return
    try:
        registry.record_redirect(
            previous_url=previous_url,
            current_url=current_url,
            family=SourceKind.GENERIC_WEB,
            reason="site_redirect",
        )
    except ValueError:
        return


def _preferred_feed_family(items: tuple[SiteFeedCandidate, ...]) -> str | None:
    families = {item.family for item in items}
    if SourceKind.RSS_ATOM.value in families:
        return SourceKind.RSS_ATOM.value
    if SourceKind.JSON_FEED.value in families:
        return SourceKind.JSON_FEED.value
    return None


def _publisher_slug(url: str) -> str:
    host = urlparse(canonicalize_url(url)).hostname or "unknown"
    return host


def _site_origin(url: str) -> str:
    canonical = canonicalize_url(url)
    parsed = urlparse(canonical)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("site origin requires HTTPS hostname")
    return f"https://{parsed.netloc}/"


def _same_origin(origin: str, candidate: str) -> bool:
    try:
        left = urlparse(canonicalize_url(origin)).hostname
        right = urlparse(canonicalize_url(candidate)).hostname
    except ValueError:
        return False
    return bool(left and right and left == right)


def _absolute_http_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    candidate = urljoin(base_url, value)
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


class _AlternateFeedParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        values = {key.lower(): (value or "") for key, value in attrs}
        rel_tokens = values.get("rel", "").lower().split()
        if "alternate" not in rel_tokens:
            return
        href = values.get("href", "").strip()
        mime_type = values.get("type", "").split(";", 1)[0].strip().lower()
        title = values.get("title", "").strip()
        if href:
            self.links.append((href, mime_type, title))
