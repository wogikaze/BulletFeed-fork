"""Turn index-feed article links into unconfirmed publisher-feed probes.

Does not fetch, subscribe, or write Claims. Site RSS confirmation stays on
``discover_feeds_from_site_url``. Index hosts themselves are never treated as
the original publisher.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from app.config import Settings
from app.observability import record
from app.services.japanese_source_catalog import (
    INDEX_DERIVED_SLUG_PREFIX,
    japanese_feed_authority_class,
    japanese_index_feed_urls,
)
from app.services.source_catalog import SourceKind
from app.services.source_discovery import DiscoveryHint
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_feed_discover import well_known_feed_urls
from app.services.source_registry import canonicalize_url
from app.services.url_safety import validate_url_shape

_MAX_PUBLISHERS = 8


def is_japanese_index_feed(url: str) -> bool:
    try:
        canonical = canonicalize_url(url)
    except ValueError:
        canonical = url.strip().rstrip("/")
    return canonical in {canonicalize_url(item) for item in japanese_index_feed_urls()}


def unwrap_index_article_url(raw: str) -> str:
    """Map an index permalink back to the original article URL when possible.

    Hatena Bookmark often wraps ``https://example.com/post`` as
    ``https://b.hatena.ne.jp/entry/s/example.com/post``. The wrapper host is
    not the publisher.
    """
    stripped = raw.strip()
    parsed = urlparse(stripped)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = unquote(parsed.path or "")
    if host == "b.hatena.ne.jp" and path.startswith("/entry/"):
        rest = path[len("/entry/") :]
        if rest.startswith("s/"):
            rest = rest[2:]
        if rest.startswith("http://") or rest.startswith("https://"):
            return rest
        if rest:
            return f"https://{rest}"
    return stripped


def original_article_hosts(
    items: Sequence[Mapping[str, object]],
    *,
    index_url: str,
    limit: int = _MAX_PUBLISHERS,
) -> tuple[str, ...]:
    """Unique public article hosts linked from an index feed preview."""
    index_host = (urlparse(index_url).hostname or "").lower().rstrip(".")
    hosts: list[str] = []
    seen: set[str] = set()
    for item in items:
        raw = item.get("link") or item.get("url")
        if not isinstance(raw, str) or not raw.strip():
            continue
        article_url = unwrap_index_article_url(raw)
        host = (urlparse(article_url).hostname or "").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        if not host or host == index_host or host in seen:
            continue
        if japanese_feed_authority_class(f"https://{host}/") is not None:
            continue
        try:
            validate_url_shape(f"https://{host}/", source_name="index-publisher")
        except HTTPException:
            continue
        seen.add(host)
        hosts.append(host)
        if len(hosts) >= max(1, int(limit)):
            break
    return tuple(hosts)


def publisher_feed_hints_from_hosts(
    hosts: Sequence[str],
    *,
    concept_ids: tuple[str, ...] = (),
) -> tuple[DiscoveryHint, ...]:
    """One unconfirmed same-origin feed probe per original article host."""
    hints: list[DiscoveryHint] = []
    for host in hosts:
        site = f"https://{host}/"
        probes = well_known_feed_urls(site, limit=1)
        if not probes:
            continue
        feed_url = probes[0]
        hints.append(
            DiscoveryHint(
                url=feed_url,
                provenance=DiscoveryProvenance.WEBSITE_FEED.value,
                family=SourceKind.RSS_ATOM,
                concept_ids=concept_ids,
                title=f"{host} site feed probe",
                publisher_slug=f"{INDEX_DERIVED_SLUG_PREFIX}{host.replace('.', '-')}",
                publisher_name=host,
                homepage_url=site,
                why=(
                    "Unconfirmed site feed probe from an index-feed article host; "
                    "not publisher authority and not Claim evidence"
                ),
                display_name=f"{host} site feed probe",
            )
        )
    return tuple(hints)


def homepage_url_from_probe(probe_url: str) -> str:
    """Same-origin homepage for an unconfirmed well-known feed probe."""
    host = (urlparse(probe_url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return f"https://{host}/"


async def confirm_index_publisher_feed(
    settings: Settings,
    *,
    probe_url: str,
) -> str | None:
    """Replace an unconfirmed ``/feed`` probe with HTML ``rel=alternate`` when present.

    Does not subscribe, persist the registry, or write Claims. Fetch failures
    return no feed, so callers cannot approve an unverified probe.
    """
    from app.services.source_feed_discover import discover_feeds_from_site_url

    try:
        validate_url_shape(probe_url, source_name="index-publisher")
    except HTTPException:
        return None
    homepage = homepage_url_from_probe(probe_url)
    try:
        validate_url_shape(homepage, source_name="index-publisher")
    except HTTPException:
        return None
    try:
        result = await discover_feeds_from_site_url(
            settings,
            homepage,
            persist_registry=False,
            probe_well_known=False,
        )
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001 - live HTML confirm must not fail approval
        return None
    origin_host = (urlparse(homepage).hostname or "").lower().rstrip(".")
    for item in result.items:
        if item.family != SourceKind.RSS_ATOM.value:
            continue
        if item.discovery_method != "html_link_alternate":
            continue
        if not item.canonical_url:
            continue
        if (urlparse(item.canonical_url).hostname or "").lower().rstrip(".") != origin_host:
            continue
        try:
            confirmed = await discover_feeds_from_site_url(
                settings,
                item.canonical_url,
                persist_registry=False,
                probe_well_known=False,
            )
        except (HTTPException, ValueError):
            continue
        except Exception as exc:  # noqa: BLE001 - live feed confirmation must fail closed
            record("index_publisher_feed_confirmation_failed", error=type(exc).__name__)
            continue
        for feed in confirmed.items:
            if (
                feed.family == SourceKind.RSS_ATOM.value
                and feed.canonical_url
                and (urlparse(feed.canonical_url).hostname or "").lower().rstrip(".")
                == origin_host
            ):
                return feed.canonical_url
    return None


def publisher_feed_hints_from_index_preview(
    items: Sequence[Mapping[str, object]],
    *,
    index_url: str,
    concept_ids: tuple[str, ...] = (),
    limit: int = _MAX_PUBLISHERS,
) -> tuple[DiscoveryHint, ...]:
    if not is_japanese_index_feed(index_url):
        return ()
    hosts = original_article_hosts(items, index_url=index_url, limit=limit)
    return publisher_feed_hints_from_hosts(hosts, concept_ids=concept_ids)
