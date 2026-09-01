"""Real-network G1 measurement using the production site-feed discovery path.

Development rows are the default.  Blind rows require an explicit final-run
opt-in so routine development cannot accidentally inspect the frozen blind
slice.  This module performs no source-specific patching and never writes
Observations, Claims, or subscriptions.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import HTTPException

from app.config import Settings
from app.evaluation.product_gap_c1 import G0Source, load_g0_sources
from app.services.source_catalog import SourceKind
from app.services.source_feed_discover import discover_feeds_from_site_url
from app.services.source_registry import SourceRegistry, canonicalize_url

Split = Literal["dev", "blind"]


def _canonical(url: str) -> str:
    try:
        return canonicalize_url(url)
    except ValueError:
        return url.strip().rstrip("/")


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(canonicalize_url(url)).hostname
    except ValueError:
        return None


def _measurement_settings(row: G0Source, *, timeout_seconds: float) -> Settings:
    hosts = {host for host in (_host(row.site_url), _host(row.feed_url), _host(row.canonical_url)) if host}
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


def _classify_http_failure(exc: HTTPException) -> str:
    if exc.status_code == 403:
        return "policy_blocked"
    if exc.status_code in {401, 407, 422}:
        return "unsubscribable"
    return "acquisition_failed"


async def measure_live_g1(
    gold_dir: Path,
    *,
    split: Split = "dev",
    allow_blind_final: bool = False,
    limit: int | None = None,
    timeout_seconds: float = 10.0,
    delay_seconds: float = 0.10,
) -> dict[str, Any]:
    if split == "blind" and not allow_blind_final:
        raise ValueError("blind measurement requires allow_blind_final=True")

    sources = load_g0_sources(gold_dir / "sources.json")
    selected = [row for row in sources if row.split == split]
    if limit is not None:
        selected = selected[: max(0, int(limit))]

    feed_total = 0
    feed_hits = 0
    precision_at_3_scores: list[float] = []
    japanese_feed_total = 0
    japanese_feed_hits = 0
    no_feed_total = 0
    fallback_hits = 0
    family_total: dict[str, int] = defaultdict(int)
    family_hits: dict[str, int] = defaultdict(int)
    rows: list[dict[str, Any]] = []

    for index, row in enumerate(selected):
        if row.policy_status != "eligible":
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "language": row.language,
                    "status": "policy_blocked",
                    "detail": "gold_policy_status_not_eligible",
                }
            )
            continue

        settings = _measurement_settings(row, timeout_seconds=timeout_seconds)
        registry = SourceRegistry()
        try:
            result = await discover_feeds_from_site_url(
                settings,
                row.site_url,
                registry=registry,
                persist_registry=False,
            )
        except HTTPException as exc:
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "language": row.language,
                    "status": _classify_http_failure(exc),
                    "http_status": exc.status_code,
                }
            )
            if row.has_feed and row.feed_url:
                feed_total += 1
                family_total[row.family] += 1
                if row.language == "ja":
                    japanese_feed_total += 1
            else:
                no_feed_total += 1
            continue
        except Exception as exc:  # noqa: BLE001 - unknown failures must remain visible in evaluation
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "language": row.language,
                    "status": "unclassified",
                    "exception_type": type(exc).__name__,
                }
            )
            if row.has_feed and row.feed_url:
                feed_total += 1
                family_total[row.family] += 1
                if row.language == "ja":
                    japanese_feed_total += 1
            else:
                no_feed_total += 1
            continue

        candidate_urls = [_canonical(item.canonical_url) for item in result.items]
        if row.has_feed and row.feed_url:
            feed_total += 1
            family_total[row.family] += 1
            gold_feed = _canonical(row.feed_url)
            found = gold_feed in candidate_urls
            window = candidate_urls[:3]
            precision_at_3 = (sum(1 for item in window if item == gold_feed) / len(window)) if window else 0.0
            feed_hits += int(found)
            precision_at_3_scores.append(precision_at_3)
            in_top3 = gold_feed in window
            family_hits[row.family] += int(found)
            if row.language == "ja":
                japanese_feed_total += 1
                japanese_feed_hits += int(found)
            status = "ok" if found else "undiscovered"
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "language": row.language,
                    "status": status,
                    "expected_feed": gold_feed,
                    "candidate_count": len(candidate_urls),
                    "candidate_urls": candidate_urls,
                    "top3_hit": in_top3,
                }
            )
        else:
            no_feed_total += 1
            fallback = bool(
                result.preferred_family == SourceKind.GENERIC_WEB.value
                and result.items
                and result.items[0].family == SourceKind.GENERIC_WEB.value
            )
            fallback_hits += int(fallback)
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "language": row.language,
                    "status": "ok" if fallback else "fallback_failed",
                    "candidate_count": len(candidate_urls),
                    "candidate_urls": candidate_urls,
                }
            )

        if delay_seconds > 0 and index + 1 < len(selected):
            await asyncio.sleep(delay_seconds)

    family_recall = {
        family: family_hits[family] / total if total else 0.0
        for family, total in sorted(family_total.items())
    }
    status_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        status_counts[str(row["status"])] += 1

    feed_recall = feed_hits / feed_total if feed_total else 0.0
    precision_at_3 = (
        sum(precision_at_3_scores) / len(precision_at_3_scores) if precision_at_3_scores else 0.0
    )
    return {
        "artifact_version": "product-gap-c1-g1-measurement-v1",
        "path": "production_confirm",
        "sample_complete": limit is None,
        "split": split,
        "blind_final": split == "blind" and allow_blind_final,
        "selected_sources": len(selected),
        "feed_sources": feed_total,
        "metrics": {
            "feed_recall": feed_recall,
            "precision_at_3": precision_at_3,
            "japanese_feed_recall": (
                japanese_feed_hits / japanese_feed_total if japanese_feed_total else 0.0
            ),
            "family_recall": family_recall,
            "no_feed_fallback_rate": fallback_hits / no_feed_total if no_feed_total else None,
        },
        "status_counts": dict(sorted(status_counts.items())),
        "rows": rows,
    }
