"""Enrich summary-only RSS entries from the public article page.

Does not persist SnapshotStore bodies. Discovery-only pages stay ineligible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.config import Settings
from app.services.web_normalize import NormalizedDocument, normalize_web_snapshot
from app.services.web_snapshots import (
    ACQUISITION_STATIC_HTTP,
    RobotsDecision,
    WebSnapshot,
    fetch_html_page,
)

ENRICHMENT_VERSION = "rss-article-enrichment-v1"
SUMMARY_ONLY_MAX_CHARS = 280
ARTICLE_TEXT_MAX_CHARS = 4000


@dataclass(frozen=True)
class ArticleEnrichment:
    article_text: str
    evidence_locator: str
    article_content_hash: str
    fetched: bool
    reason: str


def document_main_text(document: NormalizedDocument, *, max_chars: int = ARTICLE_TEXT_MAX_CHARS) -> str:
    parts: list[str] = []
    for section in document.sections:
        if section.heading:
            parts.append(section.heading)
        for block in section.blocks:
            if block.text.strip():
                parts.append(block.text.strip())
    text = "\n".join(parts).strip()
    return text[:max_chars]


def first_evidence_locator(document: NormalizedDocument) -> str:
    for section in document.sections:
        for block in section.blocks:
            locator = block.locator
            start = locator.start_offset if locator.start_offset is not None else 0
            end = locator.end_offset if locator.end_offset is not None else start
            return f"dom:{locator.dom_path};off:{start}-{end}"
        locator = section.locator
        return f"dom:{locator.dom_path};off:0-0"
    return "dom:html;off:0-0"


def is_summary_only(summary: str, *, feed_body: str = "") -> bool:
    if feed_body.strip() and len(feed_body.strip()) > SUMMARY_ONLY_MAX_CHARS:
        return False
    return len(summary.strip()) <= SUMMARY_ONLY_MAX_CHARS


def snapshot_from_html(
    *,
    url: str,
    body: bytes,
    robots: RobotsDecision,
    retrieved_at: str,
) -> WebSnapshot:
    digest = hashlib.sha256(body).hexdigest()
    return WebSnapshot(
        snapshot_id=f"rssart_{digest[:16]}",
        canonical_url=url,
        retrieved_at=retrieved_at,
        content_hash=digest,
        status_code=200,
        headers=(("content-type", "text/html; charset=utf-8"),),
        body=body,
        etag=None,
        last_modified=None,
        robots=robots,
        final_url=url,
        acquisition_mode=ACQUISITION_STATIC_HTTP,
    )


def enrich_html_bytes(
    *,
    url: str,
    body: bytes,
    robots: RobotsDecision,
    retrieved_at: str,
) -> ArticleEnrichment:
    snapshot = snapshot_from_html(url=url, body=body, robots=robots, retrieved_at=retrieved_at)
    document = normalize_web_snapshot(snapshot)
    if document.rejected:
        return ArticleEnrichment(
            article_text="",
            evidence_locator="",
            article_content_hash=snapshot.content_hash,
            fetched=True,
            reason=document.reject_reason or "normalize_rejected",
        )
    text = document_main_text(document)
    if not text:
        return ArticleEnrichment(
            article_text="",
            evidence_locator="",
            article_content_hash=snapshot.content_hash,
            fetched=True,
            reason="empty_main_text",
        )
    return ArticleEnrichment(
        article_text=text,
        evidence_locator=first_evidence_locator(document),
        article_content_hash=snapshot.content_hash,
        fetched=True,
        reason="enriched",
    )


async def enrich_feed_item(
    settings: Settings,
    item: dict[str, Any],
    *,
    retrieved_at: str,
) -> dict[str, Any]:
    """Return a copy of the feed item, adding article fields when needed."""
    summary = item.get("summary") if isinstance(item.get("summary"), str) else ""
    feed_body = item.get("content") if isinstance(item.get("content"), str) else ""
    link = item.get("link") if isinstance(item.get("link"), str) else ""
    if not link or not is_summary_only(summary, feed_body=feed_body):
        return {**item, "article_fetch_skipped": True}
    try:
        body, final_url, robots = await fetch_html_page(settings, link)
    except HTTPException as exc:
        return {**item, "article_fetch_failed": str(exc.detail), "article_text": ""}
    except Exception as exc:  # noqa: BLE001 - crawl must not die on one article
        return {**item, "article_fetch_failed": str(exc), "article_text": ""}
    enrichment = enrich_html_bytes(
        url=final_url or link,
        body=body,
        robots=robots,
        retrieved_at=retrieved_at,
    )
    if enrichment.reason != "enriched":
        return {**item, "article_fetch_failed": enrichment.reason, "article_text": ""}
    return {
        **item,
        "article_text": enrichment.article_text,
        "evidence_locator": enrichment.evidence_locator,
        "article_content_hash": enrichment.article_content_hash,
    }
