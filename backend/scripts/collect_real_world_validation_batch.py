"""Collect provenance-bound release and feed events for the M2 corpus.

This tool only uses fixed public HTTPS endpoints and stores the captured
response bytes for each event. It does not generate labels or read blind data.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import feedparser
import httpx

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "gold" / "real_world_validation" / "v01"
USER_AGENT = "BulletFeed/validation-collector (+https://github.com/wogikaze/BulletFeed-fork)"
ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "aws.amazon.com",
        "blog.chromium.org",
        "blog.jetbrains.com",
        "blog.python.org",
        "blog.rust-lang.org",
        "blogs.oracle.com",
        "developer.apple.com",
        "developers-jp.googleblog.com",
        "github.blog",
        "kubernetes.io",
        "pypi.org",
        "planetpython.org",
        "registry.npmjs.org",
        "techblog.lycorp.co.jp",
        "crates.io",
        "status.npmjs.org",
        "www.githubstatus.com",
    }
)
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

NPM_PACKAGES = (
    "react",
    "react-dom",
    "typescript",
    "vite",
    "eslint",
    "prettier",
    "webpack",
    "express",
    "fastify",
    "next",
    "vue",
    "nuxt",
    "svelte",
    "@sveltejs/kit",
    "@angular/core",
    "rxjs",
    "lodash",
    "axios",
    "zod",
    "prisma",
    "@prisma/client",
    "drizzle-orm",
    "tailwindcss",
    "postcss",
    "koa",
    "hono",
    "@nestjs/core",
    "graphql",
    "@apollo/server",
    "@trpc/server",
    "vitest",
    "jest",
    "playwright-core",
    "puppeteer",
    "electron",
    "three",
    "d3",
    "chalk",
    "commander",
    "dotenv",
)

PYPI_PACKAGES = (
    "fastapi",
    "pydantic",
    "requests",
    "httpx",
    "django",
    "flask",
    "sqlalchemy",
    "alembic",
    "uvicorn",
    "starlette",
    "pytest",
    "ruff",
    "black",
    "mypy",
    "numpy",
    "pandas",
    "scipy",
    "torch",
    "transformers",
    "jupyter",
    "ipython",
    "celery",
    "redis",
    "boto3",
    "botocore",
    "cryptography",
    "bcrypt",
    "typer",
    "click",
    "rich",
    "attrs",
    "anyio",
    "trio",
    "beautifulsoup4",
    "lxml",
    "feedparser",
    "bleach",
    "semgrep",
    "bandit",
    "pip-audit",
)

CRATES = (
    "serde",
    "tokio",
    "reqwest",
    "anyhow",
    "thiserror",
    "clap",
    "axum",
    "actix-web",
    "hyper",
    "rustls",
    "ring",
    "rand",
    "regex",
    "syn",
    "quote",
    "proc-macro2",
    "wasm-bindgen",
    "wgpu",
    "bevy",
    "time",
    "chrono",
    "uuid",
    "tracing",
    "tracing-subscriber",
    "tower",
    "tower-http",
    "bytes",
    "futures",
    "rayon",
    "itertools",
    "sqlx",
    "diesel",
    "scraper",
    "notify",
    "cargo_metadata",
    "git2",
    "url",
    "serde_json",
    "toml",
    "once_cell",
)

RSS_FEEDS = (
    ("rust-blog", "https://blog.rust-lang.org/feed.xml"),
    ("python-blog", "https://blog.python.org/feeds/posts/default"),
    ("kubernetes-blog", "https://kubernetes.io/feed.xml"),
    ("kotlin-blog", "https://blog.jetbrains.com/kotlin/feed/"),
    ("github-blog", "https://github.blog/feed/"),
    ("planet-python", "https://planetpython.org/rss20.xml"),
    ("aws-japan-whats-new", "https://aws.amazon.com/jp/about-aws/whats-new/recent/feed/"),
    ("aws-japan-security", "https://aws.amazon.com/jp/security/security-bulletins/rss/feed/"),
    ("chromium-japanese", "https://blog.chromium.org/feeds/posts/default/-/Japanese?alt=rss"),
    ("apple-japan-news", "https://developer.apple.com/jp/news/rss/news.rss"),
    ("google-developers-jp", "https://developers-jp.googleblog.com/feeds/posts/default?alt=rss"),
    ("jetbrains-japan", "https://blog.jetbrains.com/ja/feed/"),
    ("lycorp-japan-engineering", "https://techblog.lycorp.co.jp/ja/feed/index.xml"),
)

STATUS_INCIDENT_FEEDS = (
    (
        "github-status",
        "GitHub Status",
        "https://www.githubstatus.com/api/v2/incidents.json",
        "https://www.githubstatus.com",
    ),
    (
        "npm-status",
        "npm Status",
        "https://status.npmjs.org/api/v2/incidents.json",
        "https://status.npmjs.org",
    ),
)


@dataclass(frozen=True)
class VersionTarget:
    registry: str
    package: str
    version: str
    fetch_url: str
    canonical_url: str
    occurred_at: str | None
    occurred_at_provenance: str | None
    evidence_locator: str


@dataclass(frozen=True)
class Captured:
    url: str
    final_url: str
    status: int
    content_type: str | None
    requested_at: str
    body: bytes


def _stamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _assert_public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"collector URL is outside the fixed public allowlist: {url}")


async def _get(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    *,
    max_bytes: int,
) -> Captured | None:
    _assert_public_https(url)
    async with semaphore:
        for attempt in range(3):
            requested_at = _stamp()
            try:
                response = await client.get(url)
                if response.status_code != 200 or len(response.content) > max_bytes:
                    return None
                return Captured(
                    url=url,
                    final_url=str(response.url),
                    status=response.status_code,
                    content_type=response.headers.get("content-type"),
                    requested_at=requested_at,
                    body=response.content,
                )
            except (httpx.HTTPError, TimeoutError):
                if attempt == 2:
                    return None
                await asyncio.sleep(2**attempt)
    return None


async def _npm_targets(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    package: str,
) -> tuple[VersionTarget, ...]:
    encoded = quote(package, safe="@/")
    root = await _get(client, semaphore, f"https://registry.npmjs.org/{encoded}", max_bytes=16 * 1024 * 1024)
    if root is None:
        return ()
    try:
        payload = json.loads(root.body)
        versions = payload.get("versions", {})
        times = payload.get("time", {})
        if not isinstance(versions, dict) or not isinstance(times, dict):
            return ()
        names = [
            name
            for name in versions
            if name not in {"created", "modified"} and isinstance(times.get(name), str)
        ]
        names.sort(key=lambda name: (str(times.get(name)), name), reverse=True)
    except (TypeError, ValueError):
        return ()
    return tuple(
        VersionTarget(
            registry="npm",
            package=package,
            version=version,
            fetch_url=f"https://registry.npmjs.org/{encoded}/{quote(version, safe='')}",
            canonical_url=f"https://www.npmjs.com/package/{encoded}/v/{quote(version, safe='')}",
            occurred_at=str(times[version]),
            occurred_at_provenance="npm.version.time",
            evidence_locator="json_pointer:/version",
        )
        for version in names[:5]
    )


async def _pypi_targets(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    package: str,
) -> tuple[VersionTarget, ...]:
    encoded = quote(package, safe="")
    root = await _get(client, semaphore, f"https://pypi.org/pypi/{encoded}/json", max_bytes=16 * 1024 * 1024)
    if root is None:
        return ()
    try:
        payload = json.loads(root.body)
        releases = payload.get("releases", {})
        if not isinstance(releases, dict):
            return ()
        versions: list[tuple[str, str]] = []
        for version, files in releases.items():
            if not isinstance(files, list):
                continue
            timestamps = [
                item.get("upload_time_iso_8601")
                for item in files
                if isinstance(item, dict) and isinstance(item.get("upload_time_iso_8601"), str)
            ]
            if timestamps:
                versions.append((version, max(timestamps)))
        versions.sort(key=lambda item: (item[1], item[0]), reverse=True)
    except (TypeError, ValueError):
        return ()
    return tuple(
        VersionTarget(
            registry="pypi",
            package=package,
            version=version,
            fetch_url=f"https://pypi.org/pypi/{encoded}/{quote(version, safe='')}/json",
            canonical_url=f"https://pypi.org/project/{encoded}/{quote(version, safe='')}/",
            occurred_at=timestamp,
            occurred_at_provenance="pypi.releases.upload_time_iso_8601",
            evidence_locator="json_pointer:/info/version",
        )
        for version, timestamp in versions[:5]
    )


async def _crate_targets(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    package: str,
) -> tuple[VersionTarget, ...]:
    encoded = quote(package, safe="")
    root = await _get(
        client,
        semaphore,
        f"https://crates.io/api/v1/crates/{encoded}",
        max_bytes=16 * 1024 * 1024,
    )
    if root is None:
        return ()
    try:
        payload = json.loads(root.body)
        versions = payload.get("versions", [])
        if not isinstance(versions, list):
            return ()
        available = [
            item
            for item in versions
            if isinstance(item, dict)
            and not item.get("yanked")
            and isinstance(item.get("num"), str)
            and isinstance(item.get("created_at"), str)
        ]
        available.sort(key=lambda item: (str(item["created_at"]), str(item["num"])), reverse=True)
    except (TypeError, ValueError):
        return ()
    return tuple(
        VersionTarget(
            registry="crates",
            package=package,
            version=str(item["num"]),
            fetch_url=f"https://crates.io/api/v1/crates/{encoded}/{quote(str(item['num']), safe='')}",
            canonical_url=f"https://crates.io/crates/{encoded}/{quote(str(item['num']), safe='')}",
            occurred_at=str(item["created_at"]),
            occurred_at_provenance="crates.version.created_at",
            evidence_locator="json_pointer:/version/num",
        )
        for item in available[:5]
    )


async def _discover_targets(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> tuple[VersionTarget, ...]:
    tasks = [
        _npm_targets(client, semaphore, package)
        for package in NPM_PACKAGES
    ]
    tasks.extend(_pypi_targets(client, semaphore, package) for package in PYPI_PACKAGES)
    tasks.extend(_crate_targets(client, semaphore, package) for package in CRATES)
    batches = await asyncio.gather(*tasks)
    return tuple(target for batch in batches for target in batch)


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _language(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    japanese_count = len(JAPANESE_RE.findall(text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    if japanese_count >= 3 and japanese_count >= latin_count * 0.25:
        return "ja"
    if japanese_count:
        return "mixed"
    return "en"


def _json_record(
    target: VersionTarget,
    captured: Captured,
    source_id: str,
    event_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    body_text = captured.body.decode("utf-8", errors="replace")
    evidence = target.version if target.version in body_text else target.package
    if evidence not in body_text:
        raise ValueError(f"captured {target.fetch_url} has no stable evidence token")
    language = _language(captured.body)
    artifact = f"artifacts/{source_id}/body.bin"
    source = {
        "source_id": source_id,
        "canonical_url": target.canonical_url,
        "publisher": f"{target.registry} registry / {target.package}",
        "source_family": "package_registry",
        "information_type": "release",
        "language": language,
        "collected_at": captured.requested_at,
        "content_hash": hashlib.sha256(captured.body).hexdigest(),
        "evidence_locator": target.evidence_locator,
        "event_id": event_id,
        "split": "",
        "source_role": "event_page",
        "fetch": {
            "fetch_kind": "live_https",
            "url": target.fetch_url,
            "requested_at": captured.requested_at,
            "http_status": captured.status,
            "content_type": captured.content_type,
            "final_url": captured.final_url,
            "etag": None,
            "last_modified": None,
            "artifact_relpath": artifact,
        },
        "evidence_text": evidence,
        "normalized_evidence": f"{target.package} {target.version} release metadata from {target.registry}",
        "static_fetch_ok": True,
        "static_normalize_insufficient": False,
        "js_render_would_recover": False,
    }
    event = {
        "event_id": event_id,
        "split": "",
        "title": f"{target.package} {target.version}",
        "information_type": "release",
        "language": language,
        "redundancy_group": f"rg_{event_id}",
        "mirror_group": f"mg_{event_id}",
        "record_kind": "event_update",
        "is_real_event": True,
        "published_at": target.occurred_at,
        "updated_at": None,
        "observed_at": captured.requested_at,
        "effective_at": None,
        "occurred_at": target.occurred_at,
        "occurred_at_provenance": target.occurred_at_provenance,
        "occurred_at_basis": f"version timestamp from {target.registry} metadata"
        if target.occurred_at
        else None,
        "provenance": f"{target.registry}-api:{target.fetch_url}",
    }
    return source, event


def _rss_record(
    feed_slug: str,
    feed_url: str,
    entry: Any,
    captured: Captured,
    source_id: str,
    event_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    title = str(entry.get("title") or "").strip()
    link = str(entry.get("link") or "").strip()
    if not title or not link or not link.startswith("https://"):
        return None
    body_text = captured.body.decode("utf-8", errors="replace")
    evidence = title if title in body_text else link
    if evidence not in body_text:
        return None
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    occurred_at = None
    provenance = None
    if parsed_time is not None:
        occurred_at = datetime.fromtimestamp(calendar.timegm(parsed_time), tz=UTC).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
        provenance = "rss.published" if entry.get("published_parsed") else "rss.updated"
    entry_text = " ".join(
        str(entry.get(key) or "")
        for key in ("title", "summary", "description", "content")
    )
    language = _language(entry_text.encode("utf-8"))
    artifact = f"artifacts/{source_id}/body.bin"
    source = {
        "source_id": source_id,
        "canonical_url": link,
        "publisher": feed_slug,
        "source_family": "rss_atom",
        "information_type": "roadmap_changelog",
        "language": language,
        "collected_at": captured.requested_at,
        "content_hash": hashlib.sha256(captured.body).hexdigest(),
        "evidence_locator": f"feed_entry:{link}",
        "event_id": event_id,
        "split": "",
        "source_role": "event_page",
        "fetch": {
            "fetch_kind": "live_https",
            "url": feed_url,
            "requested_at": captured.requested_at,
            "http_status": captured.status,
            "content_type": captured.content_type,
            "final_url": captured.final_url,
            "etag": None,
            "last_modified": None,
            "artifact_relpath": artifact,
        },
        "evidence_text": evidence,
        "normalized_evidence": f"{title} from {feed_slug} RSS/Atom feed",
        "static_fetch_ok": True,
        "static_normalize_insufficient": False,
        "js_render_would_recover": False,
    }
    event = {
        "event_id": event_id,
        "split": "",
        "title": title,
        "information_type": "roadmap_changelog",
        "language": language,
        "redundancy_group": f"rg_{event_id}",
        "mirror_group": f"mg_{event_id}",
        "record_kind": "event_update",
        "is_real_event": True,
        "published_at": occurred_at,
        "updated_at": None,
        "observed_at": captured.requested_at,
        "effective_at": None,
        "occurred_at": occurred_at,
        "occurred_at_provenance": provenance,
        "occurred_at_basis": f"RSS timestamp from {feed_url}" if occurred_at else None,
        "provenance": f"rss-fetch:{feed_url}",
    }
    return source, event


async def _status_incident_rows(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    limit: int,
) -> list[tuple[dict[str, Any], dict[str, Any], bytes]]:
    rows: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []
    for feed_slug, publisher, index_url, homepage in STATUS_INCIDENT_FEEDS:
        index = await _get(client, semaphore, index_url, max_bytes=8 * 1024 * 1024)
        if index is None:
            continue
        try:
            incidents = json.loads(index.body).get("incidents", [])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(incidents, list):
            continue
        for incident in incidents[:limit]:
            if not isinstance(incident, dict):
                continue
            incident_id = incident.get("id")
            if not isinstance(incident_id, str) or not incident_id:
                continue
            incident_url = f"{homepage}/api/v2/incidents/{quote(incident_id, safe='')}.json"
            captured = await _get(client, semaphore, incident_url, max_bytes=1_048_576)
            if captured is None:
                continue
            try:
                payload = json.loads(captured.body)
            except (TypeError, json.JSONDecodeError):
                continue
            detail = payload.get("incident", payload) if isinstance(payload, dict) else {}
            if not isinstance(detail, dict):
                continue
            title = str(detail.get("name") or incident.get("name") or "").strip()
            if not title:
                continue
            body_text = captured.body.decode("utf-8", errors="replace")
            evidence = title if title in body_text else incident_id
            if evidence not in body_text:
                continue
            suffix = _short_hash(f"{feed_slug}|{incident_id}")
            source_id = f"src_batch_status_{_slug(feed_slug)}_{suffix}"
            event_id = f"evt_batch_status_{_slug(feed_slug)}_{suffix}"
            created_at = detail.get("created_at") or incident.get("created_at")
            updated_at = detail.get("updated_at") or incident.get("updated_at")
            language = _language(title.encode("utf-8"))
            artifact = f"artifacts/{source_id}/body.bin"
            source = {
                "source_id": source_id,
                "canonical_url": str(
                    detail.get("shortlink")
                    or incident.get("shortlink")
                    or f"{homepage}/incidents/{incident_id}"
                ),
                "publisher": publisher,
                "source_family": "statuspage",
                "information_type": "incident",
                "language": language,
                "collected_at": captured.requested_at,
                "content_hash": hashlib.sha256(captured.body).hexdigest(),
                "evidence_locator": "json_pointer:/incident/name",
                "event_id": event_id,
                "split": "",
                "source_role": "event_page",
                "fetch": {
                    "fetch_kind": "live_https",
                    "url": incident_url,
                    "requested_at": captured.requested_at,
                    "http_status": captured.status,
                    "content_type": captured.content_type,
                    "final_url": captured.final_url,
                    "etag": None,
                    "last_modified": None,
                    "artifact_relpath": artifact,
                },
                "evidence_text": evidence,
                "normalized_evidence": f"{title} from {publisher} incident history",
                "static_fetch_ok": True,
                "static_normalize_insufficient": False,
                "js_render_would_recover": False,
            }
            event = {
                "event_id": event_id,
                "split": "",
                "title": title,
                "information_type": "incident",
                "language": language,
                "redundancy_group": f"rg_{event_id}",
                "mirror_group": f"mg_{event_id}",
                "record_kind": "event_update",
                "is_real_event": True,
                "published_at": created_at,
                "updated_at": updated_at,
                "observed_at": captured.requested_at,
                "effective_at": None,
                "occurred_at": created_at,
                "occurred_at_provenance": "statuspage.created_at" if created_at else None,
                "occurred_at_basis": f"Statuspage incident timestamp from {incident_url}"
                if created_at
                else None,
                "provenance": f"statuspage-api:{incident_url}",
            }
            rows.append((source, event, captured.body))
    return rows


def _load_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_split(
    root: Path,
    split: str,
    sources: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    reserved_source_ids: set[str] = frozenset(),
    reserved_event_ids: set[str] = frozenset(),
    reserved_urls: set[str] = frozenset(),
) -> int:
    split_dir = root / split
    source_path = split_dir / "sources.json"
    event_path = split_dir / "events.json"
    index_path = split_dir / "index.json"
    existing_sources = _load_array(source_path)
    existing_events = _load_array(event_path)
    existing_index = json.loads(index_path.read_text(encoding="utf-8"))
    source_ids = {row["source_id"] for row in existing_sources}
    event_ids = {row["event_id"] for row in existing_events}
    accepted_sources: list[dict[str, Any]] = []
    accepted_events: list[dict[str, Any]] = []
    for source, event in zip(sources, events, strict=True):
        if (
            source["source_id"] in source_ids
            or source["source_id"] in reserved_source_ids
            or event["event_id"] in event_ids
            or event["event_id"] in reserved_event_ids
            or source["canonical_url"] in reserved_urls
        ):
            continue
        source_ids.add(source["source_id"])
        event_ids.add(event["event_id"])
        accepted_sources.append(source)
        accepted_events.append(event)
    _write_json(source_path, [*existing_sources, *accepted_sources])
    _write_json(event_path, [*existing_events, *accepted_events])
    existing_index["source_ids"] = [
        *existing_index["source_ids"],
        *(row["source_id"] for row in accepted_sources),
    ]
    existing_index["event_ids"] = [
        *existing_index["event_ids"],
        *(row["event_id"] for row in accepted_events),
    ]
    _write_json(index_path, existing_index)
    return len(accepted_sources)


async def _collect(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    timeout = httpx.Timeout(20.0)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
        trust_env=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/rss+xml, application/atom+xml",
        },
    ) as client:
        targets = (
            (await _discover_targets(client, semaphore))[: args.package_events]
            if args.package_events
            else ()
        )
        captures = await asyncio.gather(
            *(_get(client, semaphore, target.fetch_url, max_bytes=2 * 1024 * 1024) for target in targets)
        )
        rows: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []
        for target, captured in zip(targets, captures, strict=True):
            if captured is None:
                continue
            identity = f"{target.registry}|{target.package}|{target.version}"
            suffix = _short_hash(identity)
            source_id = f"src_batch_{_slug(target.registry)}_{_slug(target.package)}_{suffix}"
            event_id = f"evt_batch_{_slug(target.registry)}_{_slug(target.package)}_{suffix}"
            try:
                source, event = _json_record(target, captured, source_id, event_id)
            except ValueError:
                continue
            rows.append((source, event, captured.body))

        rss_rows: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []
        feed_captures = await asyncio.gather(
            *(_get(client, semaphore, url, max_bytes=4 * 1024 * 1024) for _, url in RSS_FEEDS)
        )
        for (feed_slug, feed_url), captured in zip(RSS_FEEDS, feed_captures, strict=True):
            if captured is None:
                continue
            parsed = feedparser.parse(captured.body)
            for index, entry in enumerate(parsed.entries[: args.rss_events]):
                identity = f"{feed_slug}|{entry.get('link')}|{entry.get('title')}|{index}"
                suffix = _short_hash(identity)
                source_id = f"src_batch_rss_{_slug(feed_slug)}_{suffix}"
                event_id = f"evt_batch_rss_{_slug(feed_slug)}_{suffix}"
                row = _rss_record(feed_slug, feed_url, entry, captured, source_id, event_id)
                if row is not None:
                    rss_rows.append((*row, captured.body))
        rows.extend(rss_rows)
        rows.extend(
            await _status_incident_rows(
                client,
                semaphore,
                args.status_events,
            )
        )
    sources = [row[0] for row in rows]
    events = [row[1] for row in rows]
    artifacts = [row[2] for row in rows]
    split_at = min(args.split_at, len(rows))
    for index, source in enumerate(sources):
        split = "pilot" if index < split_at else "dev"
        source["split"] = split
        events[index]["split"] = split
        artifact_path = args.output_root / source["fetch"]["artifact_relpath"]
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if not artifact_path.exists():
            artifact_path.write_bytes(artifacts[index])
    return sources, events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=CORPUS)
    parser.add_argument("--package-events", type=int, default=500)
    parser.add_argument("--rss-events", type=int, default=20)
    parser.add_argument("--status-events", type=int, default=50)
    parser.add_argument("--split-at", type=int, default=260)
    parser.add_argument("--concurrency", type=int, default=12)
    args = parser.parse_args(argv)
    if (
        args.package_events < 0
        or args.rss_events < 1
        or args.status_events < 1
        or args.concurrency < 1
    ):
        raise ValueError("collection limits must be positive")
    args.output_root.mkdir(parents=True, exist_ok=True)
    sources, events = asyncio.run(_collect(args))
    paired = list(zip(sources, events, strict=True))
    split_counts = {"pilot": 0, "dev": 0}
    for source, event in paired:
        split_counts[source["split"]] += 1
        print(f"captured {source['source_id']} split={source['split']} event={event['event_id']}")
    for split in ("pilot", "dev"):
        scoped = [(source, event) for source, event in paired if source["split"] == split]
        other_split = "dev" if split == "pilot" else "pilot"
        other_sources = _load_array(args.output_root / other_split / "sources.json")
        other_events = _load_array(args.output_root / other_split / "events.json")
        split_counts[split] = _append_split(
            args.output_root,
            split,
            [row[0] for row in scoped],
            [row[1] for row in scoped],
            reserved_source_ids={row["source_id"] for row in other_sources},
            reserved_event_ids={row["event_id"] for row in other_events},
            reserved_urls={row["canonical_url"] for row in other_sources},
        )
    print(
        json.dumps(
            {
                "collector_version": "m2-package-registry-v1",
                "captured": len(paired),
                "accepted": split_counts,
                "blind_read": False,
                "label_generation": "none",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
