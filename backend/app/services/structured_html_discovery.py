from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from app.database import Database
from app.stores.discovery_store import DiscoveryCandidate, DiscoveryStore


@dataclass(frozen=True)
class StructuredPageHint:
    canonical_url: str
    date_published: str | None
    date_modified: str | None
    schema_type: str | None


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_href: str | None = None
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []
        self.json_ld_blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical_href = values.get("href")
        if tag.lower() == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True
            self._json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_json_ld:
            self.json_ld_blocks.append("".join(self._json_ld_parts))
            self._in_json_ld = False
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_ld_parts.append(data)


def extract_structured_page_hint(html_text: str, *, page_url: str) -> StructuredPageHint:
    if len(html_text.encode()) > 5_000_000:
        raise ValueError("HTML exceeds structured metadata parser size limit")
    parser = _MetadataParser()
    parser.feed(html_text)
    canonical_url = _absolute_http_url(parser.canonical_href, page_url) or page_url
    date_published: str | None = None
    date_modified: str | None = None
    schema_type: str | None = None

    for block in parser.json_ld_blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in _iter_json_ld_nodes(payload):
            candidate_type = node.get("@type")
            types = [candidate_type] if isinstance(candidate_type, str) else candidate_type
            if not isinstance(types, list):
                types = []
            if not any(item in {"Article", "NewsArticle", "BlogPosting", "TechArticle"} for item in types):
                continue
            schema_type = next((item for item in types if isinstance(item, str)), schema_type)
            if isinstance(node.get("datePublished"), str):
                date_published = node["datePublished"]
            if isinstance(node.get("dateModified"), str):
                date_modified = node["dateModified"]
            main_entity = node.get("mainEntityOfPage")
            if isinstance(main_entity, str):
                canonical_url = _absolute_http_url(main_entity, page_url) or canonical_url
            elif isinstance(main_entity, dict) and isinstance(main_entity.get("@id"), str):
                canonical_url = _absolute_http_url(main_entity["@id"], page_url) or canonical_url
            if isinstance(node.get("url"), str) and parser.canonical_href is None:
                canonical_url = _absolute_http_url(node["url"], page_url) or canonical_url
            break

    return StructuredPageHint(
        canonical_url=canonical_url,
        date_published=date_published,
        date_modified=date_modified,
        schema_type=schema_type,
    )


def record_structured_html_candidate(
    database: Database,
    *,
    page_url: str,
    html_text: str,
    seen_at: str,
) -> DiscoveryCandidate:
    hint = extract_structured_page_hint(html_text, page_url=page_url)
    return DiscoveryStore(database).upsert(
        discovery_method="structured_html",
        discovery_url=page_url,
        target_url=hint.canonical_url,
        publisher_timestamp=hint.date_modified or hint.date_published,
        metadata={
            "schema_type": hint.schema_type,
            "date_published": hint.date_published,
            "date_modified": hint.date_modified,
        },
        seen_at=seen_at,
    )


def _iter_json_ld_nodes(value: Any):
    if isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_json_ld_nodes(item)
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_ld_nodes(item)


def _absolute_http_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    candidate = urljoin(base_url, value)
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate
