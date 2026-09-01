"""Measure live RSS article-body enrichment on the dev split.

Feed items come from a live production preview.  Summary-only items are then
sent through the production HTML enrichment path.  This produces evidence
about body acquisition without inventing labels for longitudinal updates or
article boundaries.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.evaluation.product_gap_c1 import load_g0_sources
from app.services.rss import preview_feed
from app.services.rss_article_enrichment import enrich_feed_item, is_summary_only
from app.services.source_registry import canonicalize_url

_BOILERPLATE_MARKERS = (
    "site chrome",
    "skip to content",
    "all rights reserved",
    "privacy policy",
    "cookie policy",
)
_IMPORTANT_MARKERS = (
    "important",
    "security",
    "vulnerability",
    "critical",
    "breaking",
    "deprecation",
    "release",
    "cve",
    "脆弱",
    "重要",
    "リリース",
)


def _canonical(url: str) -> str:
    try:
        return canonicalize_url(url)
    except ValueError:
        return url.strip().rstrip("/")


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(_canonical(url)).hostname
    except ValueError:
        return None


def _settings_for_urls(urls: tuple[str | None, ...], *, timeout_seconds: float) -> Settings:
    hosts = {host for url in urls if (host := _host(url))}
    aliases = set(hosts)
    for host in tuple(hosts):
        if host.startswith("www."):
            aliases.add(host[4:])
        else:
            aliases.add(f"www.{host}")
    allowlist = ",".join(sorted(aliases))
    return Settings(
        web_allowed_hosts=allowlist,
        rss_allowed_hosts=allowlist,
        request_timeout_seconds=timeout_seconds,
    )


def _is_important(title: str) -> bool:
    folded = title.casefold()
    return any(marker.casefold() in folded for marker in _IMPORTANT_MARKERS)


def _has_boilerplate_signal(article_text: str) -> bool:
    folded = article_text.casefold()
    return any(marker in folded for marker in _BOILERPLATE_MARKERS)


async def measure_live_g4(
    gold_dir: Path,
    *,
    split: str = "dev",
    max_items: int | None = 100,
    timeout_seconds: float = 10.0,
    delay_seconds: float = 0.10,
) -> dict[str, Any]:
    if split != "dev":
        raise ValueError("live G4 measurement is dev-only until final blind freeze")
    sources = load_g0_sources(gold_dir / "sources.json")
    freeze = json.loads((gold_dir / "g0_freeze.json").read_text(encoding="utf-8"))
    selected = [
        row
        for row in sources
        if row.split == split and row.policy_status == "eligible" and row.has_feed and row.feed_url
    ]
    rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    body_attempts = 0
    body_successes = 0
    important_attempts = 0
    important_successes = 0
    boilerplate_signals = 0
    item_count = 0
    for source_index, row in enumerate(selected):
        assert row.feed_url is not None
        feed_settings = _settings_for_urls((row.site_url, row.feed_url), timeout_seconds=timeout_seconds)
        retrieved_at = datetime.now(UTC).isoformat()
        try:
            preview = await preview_feed(feed_settings, row.feed_url)
            feed_items = [item for item in preview.get("items", ()) if isinstance(item, dict)]
            for item in feed_items:
                if max_items is not None and item_count >= max_items:
                    break
                item_count += 1
                title = str(item.get("title") or "")
                link = str(item.get("link") or "")
                summary = str(item.get("summary") or "")
                content = str(item.get("content") or "")
                summary_only = is_summary_only(summary, feed_body=content)
                enriched = item
                attempted = bool(link and summary_only)
                if attempted:
                    body_attempts += 1
                    if _is_important(title):
                        important_attempts += 1
                    article_settings = _settings_for_urls(
                        (row.site_url, row.feed_url, link),
                        timeout_seconds=timeout_seconds,
                    )
                    enriched = await enrich_feed_item(
                        article_settings,
                        item,
                        retrieved_at=retrieved_at,
                    )
                    has_body = bool(str(enriched.get("article_text") or "").strip())
                    body_successes += int(has_body)
                    if _is_important(title):
                        important_successes += int(has_body)
                    boilerplate_signals += int(
                        _has_boilerplate_signal(str(enriched.get("article_text") or ""))
                    )
                rows.append(
                    {
                        "source_id": row.source_id,
                        "family": row.family,
                        "title": title,
                        "link": _canonical(link) if link else None,
                        "summary_only": summary_only,
                        "article_fetch_attempted": attempted,
                        "article_fetch_succeeded": bool(str(enriched.get("article_text") or "").strip()),
                        "article_fetch_failed": enriched.get("article_fetch_failed"),
                        "evidence_locator": enriched.get("evidence_locator"),
                        "article_content_hash": enriched.get("article_content_hash"),
                        "boilerplate_signal": _has_boilerplate_signal(
                            str(enriched.get("article_text") or "")
                        ),
                        "retrieved_at": retrieved_at,
                    }
                )
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - retain per-source live failures
            status = "failed"
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "status": status,
                    "exception_type": type(exc).__name__,
                    "detail": str(exc),
                    "retrieved_at": retrieved_at,
                }
            )
        status_counts[status] += 1
        if max_items is not None and item_count >= max_items:
            break
        if delay_seconds > 0 and source_index + 1 < len(selected):
            await asyncio.sleep(delay_seconds)

    return {
        "artifact_version": "product-gap-c1-g4-measurement-v1",
        "dataset_version": freeze.get("dataset_version"),
        "path": "production_preview_then_enrich_feed_item",
        "split": split,
        "sample_complete": max_items is None,
        "selected_sources": len(selected),
        "measured_items": item_count,
        "metrics": {
            "body_success": body_successes / body_attempts if body_attempts else None,
            "important_body_recall": (
                important_successes / important_attempts if important_attempts else None
            ),
            "boilerplate_fp": None,
            "boilerplate_signal_rate": (
                boilerplate_signals / body_attempts if body_attempts else None
            ),
            "update_recall": None,
            "update_precision": None,
            "article_split": None,
        },
        "unmeasured": [
            "longitudinal_update_recall",
            "longitudinal_update_precision",
            "article_boundary_split",
        ],
        "status_counts": dict(sorted(status_counts.items())),
        "rows": rows,
    }
