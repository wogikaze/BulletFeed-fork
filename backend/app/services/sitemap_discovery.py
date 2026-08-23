from __future__ import annotations

from dataclasses import dataclass

from defusedxml import ElementTree

from app.database import Database
from app.stores.discovery_store import DiscoveryCandidate, DiscoveryStore


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    last_modified: str | None
    is_sitemap: bool


def parse_sitemap(xml_bytes: bytes) -> tuple[SitemapEntry, ...]:
    if len(xml_bytes) > 5_000_000:
        raise ValueError("sitemap exceeds parser size limit")
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ValueError("invalid sitemap XML") from exc

    root_name = _local_name(root.tag)
    if root_name not in {"urlset", "sitemapindex"}:
        raise ValueError("unsupported sitemap root")
    child_name = "url" if root_name == "urlset" else "sitemap"
    entries: list[SitemapEntry] = []
    for child in root:
        if _local_name(child.tag) != child_name:
            continue
        location = None
        last_modified = None
        for field in child:
            name = _local_name(field.tag)
            if name == "loc" and field.text:
                location = field.text.strip()
            elif name == "lastmod" and field.text:
                last_modified = field.text.strip()
        if location and location.startswith(("https://", "http://")):
            entries.append(
                SitemapEntry(
                    url=location,
                    last_modified=last_modified,
                    is_sitemap=root_name == "sitemapindex",
                )
            )
    return tuple(entries)


def record_sitemap_candidates(
    database: Database,
    *,
    sitemap_url: str,
    xml_bytes: bytes,
    seen_at: str,
) -> tuple[DiscoveryCandidate, ...]:
    store = DiscoveryStore(database)
    candidates: list[DiscoveryCandidate] = []
    for entry in parse_sitemap(xml_bytes):
        candidates.append(
            store.upsert(
                discovery_method="sitemap",
                discovery_url=sitemap_url,
                target_url=entry.url,
                publisher_timestamp=entry.last_modified,
                metadata={"is_sitemap": entry.is_sitemap},
                seen_at=seen_at,
            )
        )
    return tuple(candidates)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
