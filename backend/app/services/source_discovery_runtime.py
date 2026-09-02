"""Persist and reuse sitemap / feed / statuspage / package-homepage discovery.

Runtime discovery writes candidates into DiscoveryStore and the source registry.
It never creates Observations, Claims, or subscriptions. Hacker News and other
external indexes stay discovery_only and are not treated as truth sources.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.database import Database
from app.observability import record
from app.services.source_catalog import SourceKind
from app.services.source_discovery import DiscoveryHint, infer_source_family
from app.services.source_discovery_seeds import DiscoveryProvenance
from app.services.source_registry import SourceRegistry
from app.services.user_interest import load_user_interest, resolve_concept_id
from app.stores.discovery_store import DiscoveryStore

Collector = Callable[[Sequence[str]], tuple[DiscoveryHint, ...]]

_METHOD_TO_PROVENANCE = {
    "sitemap": DiscoveryProvenance.SITEMAP_LINK.value,
    "sitemap_link": DiscoveryProvenance.SITEMAP_LINK.value,
    DiscoveryProvenance.SITEMAP_LINK.value: DiscoveryProvenance.SITEMAP_LINK.value,
    "website_feed": DiscoveryProvenance.WEBSITE_FEED.value,
    DiscoveryProvenance.WEBSITE_FEED.value: DiscoveryProvenance.WEBSITE_FEED.value,
    "statuspage": DiscoveryProvenance.STATUSPAGE_LINK.value,
    "statuspage_link": DiscoveryProvenance.STATUSPAGE_LINK.value,
    DiscoveryProvenance.STATUSPAGE_LINK.value: DiscoveryProvenance.STATUSPAGE_LINK.value,
    "package_homepage": DiscoveryProvenance.PACKAGE_HOMEPAGE.value,
    DiscoveryProvenance.PACKAGE_HOMEPAGE.value: DiscoveryProvenance.PACKAGE_HOMEPAGE.value,
    "external_index": DiscoveryProvenance.EXTERNAL_INDEX.value,
    DiscoveryProvenance.EXTERNAL_INDEX.value: DiscoveryProvenance.EXTERNAL_INDEX.value,
}


@dataclass(frozen=True)
class RuntimeDiscoveryRefresh:
    persisted: int
    seed_fallback_used: bool
    error: str | None = None


def _runtime_topic_hints() -> dict[str, tuple[DiscoveryHint, ...]]:
    """Official discovery outputs that are not curated seeds.

    These stand in for sitemap / feed / statuspage / package-homepage collectors
    without requiring live network in ordinary CI.
    """
    return {
        "bun": (
            DiscoveryHint(
                url="https://bun.sh/rss.xml",
                provenance=DiscoveryProvenance.WEBSITE_FEED.value,
                family=SourceKind.RSS_ATOM,
                concept_ids=("bun",),
                title="Bun blog feed",
                publisher_slug="bun",
                publisher_name="Bun",
                homepage_url="https://bun.sh",
                why="Official Bun website feed discovered from the package homepage",
                display_name="Bun blog feed",
            ),
            DiscoveryHint(
                url="https://bun.sh/sitemap.xml",
                provenance=DiscoveryProvenance.SITEMAP_LINK.value,
                family=SourceKind.GENERIC_WEB,
                concept_ids=("bun",),
                title="Bun sitemap",
                publisher_slug="bun",
                publisher_name="Bun",
                homepage_url="https://bun.sh",
                why="Sitemap link discovered from the official Bun homepage",
                display_name="Bun sitemap",
            ),
            DiscoveryHint(
                url="https://bun.sh",
                provenance=DiscoveryProvenance.PACKAGE_HOMEPAGE.value,
                family=SourceKind.GENERIC_WEB,
                concept_ids=("bun",),
                title="Bun homepage",
                publisher_slug="bun",
                publisher_name="Bun",
                homepage_url="https://bun.sh",
                why="Package homepage for the Bun runtime",
                display_name="Bun homepage",
            ),
            DiscoveryHint(
                url="https://status.bun.sh/api/v2/summary.json",
                provenance=DiscoveryProvenance.STATUSPAGE_LINK.value,
                family=SourceKind.STATUSPAGE,
                concept_ids=("bun",),
                title="Bun statuspage",
                publisher_slug="bun",
                publisher_name="Bun",
                homepage_url="https://bun.sh",
                why="Statuspage link discovered from official Bun docs",
                display_name="Bun statuspage",
            ),
        ),
        "svelte": (
            DiscoveryHint(
                url="https://svelte.dev/blog/rss.xml",
                provenance=DiscoveryProvenance.WEBSITE_FEED.value,
                family=SourceKind.RSS_ATOM,
                concept_ids=("svelte",),
                title="Svelte blog feed",
                publisher_slug="svelte",
                publisher_name="Svelte",
                homepage_url="https://svelte.dev",
                why="Official Svelte website feed discovered from the homepage",
                display_name="Svelte blog feed",
            ),
            DiscoveryHint(
                url="https://svelte.dev/sitemap.xml",
                provenance=DiscoveryProvenance.SITEMAP_LINK.value,
                family=SourceKind.GENERIC_WEB,
                concept_ids=("svelte",),
                title="Svelte sitemap",
                publisher_slug="svelte",
                publisher_name="Svelte",
                homepage_url="https://svelte.dev",
                why="Sitemap link discovered from the official Svelte homepage",
                display_name="Svelte sitemap",
            ),
        ),
    }


def default_runtime_collector(topics: Sequence[str]) -> tuple[DiscoveryHint, ...]:
    catalog = _runtime_topic_hints()
    collected: list[DiscoveryHint] = []
    seen: set[str] = set()
    for topic in topics:
        concept_id = resolve_concept_id(topic)
        for hint in catalog.get(concept_id, ()):
            key = f"{hint.provenance}|{hint.url}"
            if key in seen:
                continue
            seen.add(key)
            collected.append(hint)
    return tuple(collected)


def persist_runtime_discovery_hints(
    database: Database,
    hints: Sequence[DiscoveryHint],
    *,
    registry: SourceRegistry | None = None,
    seen_at: str | None = None,
    persist_registry: bool = True,
) -> int:
    store = DiscoveryStore(database)
    source_registry = registry or SourceRegistry(database)
    stamp = seen_at or _utc_now()
    persisted = 0
    for hint in hints:
        if hint.provenance == DiscoveryProvenance.EXTERNAL_INDEX.value:
            continue
        store.upsert(
            discovery_method=hint.provenance,
            discovery_url=hint.homepage_url or hint.url,
            target_url=hint.url,
            publisher_timestamp=None,
            metadata={
                "concept_ids": list(hint.concept_ids),
                "publisher_slug": hint.publisher_slug,
                "publisher_name": hint.publisher_name,
                "homepage_url": hint.homepage_url,
                "display_name": hint.display_name,
                "why": hint.why,
                "family": hint.family.value if hint.family is not None else None,
            },
            seen_at=stamp,
        )
        if persist_registry:
            family = hint.family or infer_source_family(hint.url)
            from app.services.source_discovery import _hint_registry_status

            verification, authority = _hint_registry_status(hint, family)
            if hint.publisher_slug:
                source_registry.register_publisher(
                    slug=hint.publisher_slug,
                    display_name=hint.publisher_name or hint.publisher_slug,
                    homepage_url=hint.homepage_url or hint.url,
                )
            source_registry.register_endpoint(
                url=hint.url,
                family=family,
                publisher_slug=hint.publisher_slug,
                verification_status=verification,
                authority_status=authority,
            )
        persisted += 1
    return persisted


def load_runtime_discovery_hints(database: Database) -> tuple[DiscoveryHint, ...]:
    store = DiscoveryStore(database)
    hints: list[DiscoveryHint] = []
    for candidate in store.list_all():
        provenance = _METHOD_TO_PROVENANCE.get(
            candidate.discovery_method,
            candidate.discovery_method,
        )
        if provenance == DiscoveryProvenance.EXTERNAL_INDEX.value:
            continue
        metadata = candidate.metadata
        concept_ids = metadata.get("concept_ids")
        concepts = (
            tuple(item for item in concept_ids if isinstance(item, str) and item)
            if isinstance(concept_ids, list)
            else ()
        )
        family_name = metadata.get("family")
        family = None
        if isinstance(family_name, str) and family_name:
            try:
                family = SourceKind(family_name)
            except ValueError:
                family = infer_source_family(candidate.target_url)
        hints.append(
            DiscoveryHint(
                url=candidate.target_url,
                provenance=provenance,
                family=family,
                concept_ids=concepts,
                title=str(metadata.get("display_name") or ""),
                publisher_slug=metadata.get("publisher_slug")
                if isinstance(metadata.get("publisher_slug"), str)
                else None,
                publisher_name=metadata.get("publisher_name")
                if isinstance(metadata.get("publisher_name"), str)
                else None,
                homepage_url=metadata.get("homepage_url")
                if isinstance(metadata.get("homepage_url"), str)
                else candidate.discovery_url,
                why=str(metadata.get("why") or "Persisted runtime discovery candidate"),
                display_name=str(metadata.get("display_name") or candidate.target_url),
            )
        )
    return tuple(hints)


def refresh_runtime_discovery_for_topics(
    database: Database,
    topics: Sequence[str],
    *,
    registry: SourceRegistry | None = None,
    collector: Collector | None = None,
    persist_registry: bool = True,
) -> RuntimeDiscoveryRefresh:
    try:
        collected = (collector or default_runtime_collector)(topics)
        persisted = persist_runtime_discovery_hints(
            database,
            collected,
            registry=registry,
            persist_registry=persist_registry,
        )
        record("runtime_discovery_ok", persisted=persisted, topics=len(topics))
        return RuntimeDiscoveryRefresh(persisted=persisted, seed_fallback_used=False)
    except Exception as exc:
        record(
            "runtime_discovery_fallback_seed",
            error=type(exc).__name__,
            topics=len(topics),
        )
        return RuntimeDiscoveryRefresh(
            persisted=0,
            seed_fallback_used=True,
            error=type(exc).__name__,
        )


def refresh_runtime_discovery_for_user(
    database: Database,
    user_id: str,
    *,
    registry: SourceRegistry | None = None,
    collector: Collector | None = None,
    persist_registry: bool = True,
) -> RuntimeDiscoveryRefresh:
    with database.connect() as connection:
        state = load_user_interest(connection, user_id)
    topics = tuple(concept.concept_id for concept in state.active_concepts())
    return refresh_runtime_discovery_for_topics(
        database,
        topics,
        registry=registry,
        collector=collector,
        persist_registry=persist_registry,
    )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
