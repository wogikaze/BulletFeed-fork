"""Measure live feed parity with an independent parser on the dev split.

The same recorded feed URL is fetched once by an independent, hardened
oracle path and once through BulletFeed's production ``preview_feed`` path.
The oracle is used only to compare the two results; it is never passed to
source discovery or ranking.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from defusedxml import ElementTree as SafeElementTree
from fastapi import HTTPException, status

from app.config import Settings
from app.evaluation.product_gap_c1 import G0Source, load_g0_sources
from app.services.rss import ALLOWED_FEED_CONTENT_TYPES, preview_feed, validate_feed_url
from app.services.source_registry import canonicalize_url
from app.services.url_safety import require_global_response_peer

_MAX_REDIRECTS = 4
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


def _settings_for_feed(row: G0Source, *, timeout_seconds: float) -> Settings:
    # G3 intentionally supplies the feed URL as the oracle input.  Its host
    # may therefore be allowlisted here; this is not the G1 discovery scorer.
    hosts = {host for host in (_host(row.site_url), _host(row.feed_url)) if host}
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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _element_text(element: Any) -> str:
    return "".join(element.itertext()).strip()


def _oracle_entries(body: bytes) -> list[dict[str, str]]:
    root = SafeElementTree.fromstring(body)
    entries: list[dict[str, str]] = []
    for element in root.iter():
        kind = _local_name(element.tag)
        if kind not in {"item", "entry"}:
            continue
        title = ""
        link = ""
        link_candidates: list[tuple[int, str]] = []
        for child in element:
            child_name = _local_name(child.tag)
            if child_name == "title" and not title:
                title = _element_text(child)
            elif child_name == "link":
                candidate = str(child.attrib.get("href") or _element_text(child)).strip()
                relation = str(child.attrib.get("rel") or "").casefold()
                if not candidate or relation in {"replies", "self", "enclosure"}:
                    continue
                priority = 0 if relation in {"", "alternate"} else 1
                link_candidates.append((priority, candidate))
        if link_candidates:
            link = min(link_candidates, key=lambda item: item[0])[1]
        if title and link:
            entries.append({"title": title, "link": link})
    return entries


async def _fetch_independent(
    settings: Settings,
    url: str,
) -> tuple[bytes, str, str]:
    current = validate_feed_url(url, settings.rss_hosts)
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        for _ in range(_MAX_REDIRECTS):
            async with client.stream(
                "GET",
                current,
                follow_redirects=False,
                headers={
                    "User-Agent": settings.crawler_user_agent,
                    "Accept-Encoding": "identity",
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9",
                },
            ) as response:
                require_global_response_peer(response, source_name="G3 oracle")
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="G3 oracle redirect is invalid",
                        )
                    current = validate_feed_url(urljoin(current, location), settings.rss_hosts)
                    continue
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"G3 oracle returned HTTP {response.status_code}",
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in ALLOWED_FEED_CONTENT_TYPES:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail=f"G3 oracle content type is not allowed: {content_type or 'missing'}",
                    )
                content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
                if content_encoding not in {"", "identity"}:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="G3 oracle compressed responses are not allowed",
                    )
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > settings.max_response_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="G3 oracle response exceeded the configured limit",
                        )
                    body.extend(chunk)
                return bytes(body), _canonical(current), content_type
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="G3 oracle redirected too many times",
    )


def _normalise_entries(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalised: list[dict[str, str]] = []
    for entry in entries:
        title = str(entry.get("title") or "").strip()
        link = str(entry.get("link") or "").strip()
        if title and link:
            normalised.append({"title": title, "link": _canonical(link)})
    return normalised


def _important(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        entry
        for entry in entries
        if any(marker in entry["title"].casefold() for marker in _IMPORTANT_MARKERS)
    ]


def _entry_recall(oracle: list[dict[str, str]], production: list[dict[str, str]]) -> float:
    oracle_links = {entry["link"] for entry in oracle}
    production_links = {entry["link"] for entry in production}
    return len(oracle_links & production_links) / len(oracle_links) if oracle_links else 0.0


async def measure_live_g3(
    gold_dir: Path,
    *,
    split: str = "dev",
    limit: int | None = None,
    timeout_seconds: float = 10.0,
    delay_seconds: float = 0.10,
) -> dict[str, Any]:
    if split != "dev":
        raise ValueError("live G3 measurement is dev-only until final blind freeze")
    sources = load_g0_sources(gold_dir / "sources.json")
    freeze = json.loads((gold_dir / "g0_freeze.json").read_text(encoding="utf-8"))
    selected = [
        row
        for row in sources
        if row.split == split and row.policy_status == "eligible" and row.has_feed and row.feed_url
    ]
    if limit is not None:
        selected = selected[: max(0, int(limit))]

    raw_recall: list[float] = []
    important_recall: list[float] = []
    duplicate_rates: list[float] = []
    family_totals: dict[str, int] = defaultdict(int)
    family_hits: dict[str, int] = defaultdict(int)
    rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    failed_sources = 0

    for index, row in enumerate(selected):
        if row.feed_url is None:
            status_counts["invalid_fixture"] += 1
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "status": "invalid_fixture",
                    "detail": "feed_url_required_for_g3",
                }
            )
            continue
        family_totals[row.family] += 1
        settings = _settings_for_feed(row, timeout_seconds=timeout_seconds)
        retrieved_at = datetime.now(UTC).isoformat()
        try:
            oracle_body, oracle_final_url, oracle_content_type = await _fetch_independent(
                settings,
                row.feed_url,
            )
            oracle = _normalise_entries(_oracle_entries(oracle_body)[:20])
            production_preview = await preview_feed(settings, row.feed_url)
            production = _normalise_entries(list(production_preview.get("items") or []))
            production_links = [entry["link"] for entry in production]
            duplicate_rate = (
                (len(production_links) - len(set(production_links))) / len(production_links)
                if production_links
                else 0.0
            )
            raw = _entry_recall(oracle, production)
            oracle_important = _important(oracle)
            production_important = {entry["link"] for entry in _important(production)}
            important = (
                len({entry["link"] for entry in oracle_important} & production_important)
                / len({entry["link"] for entry in oracle_important})
                if oracle_important
                else 1.0
            )
            raw_recall.append(raw)
            important_recall.append(important)
            duplicate_rates.append(duplicate_rate)
            family_hits[row.family] += int(raw >= 1.0)
            status = "ok"
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "feed_url": _canonical(row.feed_url),
                    "oracle_final_url": oracle_final_url,
                    "oracle_content_type": oracle_content_type,
                    "oracle_entries": oracle,
                    "production_source_url": production_preview.get("source_url"),
                    "production_entries": production,
                    "raw_entry_recall": raw,
                    "important_update_recall": important,
                    "duplicate_item_rate": duplicate_rate,
                    "retrieved_at": retrieved_at,
                    "status": status,
                }
            )
        except Exception as exc:  # noqa: BLE001 - retain live failure as artifact data
            status = "failed"
            failed_sources += 1
            raw_recall.append(0.0)
            important_recall.append(0.0)
            duplicate_rates.append(0.0)
            rows.append(
                {
                    "source_id": row.source_id,
                    "family": row.family,
                    "feed_url": _canonical(row.feed_url),
                    "status": status,
                    "exception_type": type(exc).__name__,
                    "detail": str(exc),
                    "retrieved_at": retrieved_at,
                }
            )
        status_counts[status] += 1
        if delay_seconds > 0 and index + 1 < len(selected):
            await asyncio.sleep(delay_seconds)

    attempted = len(raw_recall)
    successful = attempted - failed_sources
    return {
        "artifact_version": "product-gap-c1-g3-measurement-v4",
        "dataset_version": freeze.get("dataset_version"),
        "path": "same_feed_url_independent_oracle_vs_production_preview",
        "live_oracle": True,
        "family_regression_measured": False,
        "sample_complete": limit is None,
        "split": split,
        "selected_sources": len(selected),
        "attempted_sources": attempted,
        "successful_sources": successful,
        "failed_sources": failed_sources,
        "metrics": {
            "raw_entry_recall": sum(raw_recall) / attempted if attempted else None,
            "important_update_recall": sum(important_recall) / attempted if attempted else None,
            "duplicate_item_rate": sum(duplicate_rates) / attempted if attempted else None,
            "family_recall": {
                family: family_hits[family] / total if total else 0.0
                for family, total in sorted(family_totals.items())
            },
        },
        "status_counts": dict(sorted(status_counts.items())),
        "rows": rows,
    }
