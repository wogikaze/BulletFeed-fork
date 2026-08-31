from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.database import Database
from app.services.crawler_identity import RELEASE_CRAWLER_USER_AGENT
from app.services.source_catalog import SourceKind
from app.services.source_registry import canonicalize_url
from app.services.url_safety import require_global_response_peer, validate_public_url

WEB_SNAPSHOT_SOURCE_TYPE = SourceKind.GENERIC_WEB.value
WEB_SNAPSHOT_POLL_INTERVAL_SECONDS = 300
WEB_SNAPSHOT_RETRY_BASE_SECONDS = 30
WEB_SNAPSHOT_RETRY_MAX_SECONDS = 3600
MAX_REDIRECT_ATTEMPTS = 4
DEFAULT_USER_AGENT = RELEASE_CRAWLER_USER_AGENT
ALLOWED_WEB_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
}
ROBOTS_MAX_BYTES = 64_000
SNAPSHOT_ID_PREFIX = "snap_"
ACQUISITION_STATIC_HTTP = "static_http"
ACQUISITION_BOUNDED_JS = "bounded_js_render"


class SnapshotImmutabilityError(ValueError):
    """Raised when a caller attempts to mutate a stored snapshot."""


@dataclass(frozen=True)
class RobotsDecision:
    source_url: str
    robots_url: str | None
    allowed: bool
    reason: str
    retrieved_at: str | None


@dataclass(frozen=True)
class WebSnapshot:
    snapshot_id: str
    canonical_url: str
    retrieved_at: str
    content_hash: str
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    etag: str | None
    last_modified: str | None
    robots: RobotsDecision
    final_url: str
    not_modified: bool = False
    acquisition_mode: str = ACQUISITION_STATIC_HTTP
    parent_http_snapshot_id: str | None = None
    renderer_id: str | None = None
    wait_condition: str | None = None
    render_reason: str | None = None

    @property
    def header_map(self) -> dict[str, str]:
        return {key: value for key, value in self.headers}

    @property
    def is_rendered(self) -> bool:
        return self.acquisition_mode == ACQUISITION_BOUNDED_JS


@dataclass(frozen=True)
class SnapshotStorageStats:
    snapshot_count: int
    body_bytes: int
    metadata_bytes: int
    total_bytes: int
    temporary_directory_count: int

    def as_dict(self) -> dict[str, int]:
        return {
            "snapshot_count": self.snapshot_count,
            "body_bytes": self.body_bytes,
            "metadata_bytes": self.metadata_bytes,
            "total_bytes": self.total_bytes,
            "temporary_directory_count": self.temporary_directory_count,
        }


@dataclass(frozen=True)
class SnapshotGcResult:
    scanned_count: int
    deleted_ids: tuple[str, ...]
    retained_referenced_ids: tuple[str, ...]
    temporary_directories_removed: int
    bytes_before: int
    bytes_after: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned_count": self.scanned_count,
            "deleted_ids": list(self.deleted_ids),
            "retained_referenced_ids": list(self.retained_referenced_ids),
            "temporary_directories_removed": self.temporary_directories_removed,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
        }


def content_hash_for(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def snapshot_id_for(
    *,
    canonical_url: str,
    content_hash: str,
    retrieved_at: str | None = None,
    acquisition_mode: str = ACQUISITION_STATIC_HTTP,
) -> str:
    """Stable snapshot identity.

    Content-addressed per canonical URL so identical bytes do not fork a
    second version. ``retrieved_at`` is accepted for provenance callers and
    recorded on the snapshot, but it is not part of the identity.
    Static HTTP ids stay ``url + hash`` so existing snapshots remain stable.
    Rendered snapshots include ``acquisition_mode`` so they never collide
    with the parent HTTP response.
    """
    del retrieved_at
    if acquisition_mode == ACQUISITION_STATIC_HTTP:
        material = f"{canonical_url}\n{content_hash}"
    else:
        material = f"{canonical_url}\n{content_hash}\n{acquisition_mode}"
    return f"{SNAPSHOT_ID_PREFIX}{hashlib.sha256(material.encode()).hexdigest()}"


def validate_web_url(url: str, allowed_hosts: set[str], *, allow_http: bool = False) -> str:
    return validate_public_url(url, allowed_hosts, source_name="Web", allow_http=allow_http)


def web_snapshot_backoff_seconds(failure_count: int) -> int:
    """Same exponential schedule as ``WatchSyncWorker._finish_failure``."""
    if failure_count <= 0:
        return WEB_SNAPSHOT_POLL_INTERVAL_SECONDS
    exponent = min(failure_count - 1, 16)
    return min(WEB_SNAPSHOT_RETRY_BASE_SECONDS * (2**exponent), WEB_SNAPSHOT_RETRY_MAX_SECONDS)


def record_web_snapshot_sync_result(
    database: Database,
    canonical_url: str,
    *,
    now: int,
    error: str | None = None,
) -> None:
    """Persist retry/backoff on ``source_sync_jobs``. Does not write Observations."""
    source_key = canonicalize_url(canonical_url)
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT failure_count FROM source_sync_jobs
            WHERE source_type = ? AND source_key = ?
            """,
            (WEB_SNAPSHOT_SOURCE_TYPE, source_key),
        ).fetchone()
        if error is None:
            next_run_at = now + WEB_SNAPSHOT_POLL_INTERVAL_SECONDS
            if row is None:
                connection.execute(
                    """
                    INSERT INTO source_sync_jobs (
                        source_type, source_key, next_run_at, failure_count,
                        last_attempt_at, last_success_at, last_error
                    ) VALUES (?, ?, ?, 0, ?, ?, NULL)
                    """,
                    (WEB_SNAPSHOT_SOURCE_TYPE, source_key, next_run_at, now, now),
                )
            else:
                connection.execute(
                    """
                    UPDATE source_sync_jobs
                    SET next_run_at = ?, failure_count = 0, last_attempt_at = ?,
                        last_success_at = ?, last_error = NULL
                    WHERE source_type = ? AND source_key = ?
                    """,
                    (next_run_at, now, now, WEB_SNAPSHOT_SOURCE_TYPE, source_key),
                )
        else:
            failure_count = (int(row["failure_count"]) if row is not None else 0) + 1
            next_run_at = now + web_snapshot_backoff_seconds(failure_count)
            detail = error[:500]
            if row is None:
                connection.execute(
                    """
                    INSERT INTO source_sync_jobs (
                        source_type, source_key, next_run_at, failure_count,
                        last_attempt_at, last_error
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        WEB_SNAPSHOT_SOURCE_TYPE,
                        source_key,
                        next_run_at,
                        failure_count,
                        now,
                        detail,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE source_sync_jobs
                    SET next_run_at = ?, failure_count = ?, last_attempt_at = ?,
                        last_error = ?
                    WHERE source_type = ? AND source_key = ?
                    """,
                    (
                        next_run_at,
                        failure_count,
                        now,
                        detail,
                        WEB_SNAPSHOT_SOURCE_TYPE,
                        source_key,
                    ),
                )
        connection.commit()


class SnapshotStore:
    """File-backed immutable snapshot store. Existing snapshot directories are never rewritten."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, snapshot: WebSnapshot) -> WebSnapshot:
        existing = self.get(snapshot.snapshot_id)
        if existing is not None:
            if not _snapshots_equivalent(existing, snapshot):
                raise SnapshotImmutabilityError(f"refusing to mutate stored snapshot {snapshot.snapshot_id}")
            return existing
        directory = self.root / snapshot.snapshot_id
        tmp = self.root / f".tmp-{snapshot.snapshot_id}-{secrets.token_hex(8)}"
        tmp.mkdir(parents=True, exist_ok=False)
        try:
            (tmp / "body.bin").write_bytes(snapshot.body)
            (tmp / "meta.json").write_text(
                _encode_meta(snapshot),
                encoding="utf-8",
            )
            os.replace(tmp, directory)
        except Exception:
            _rmtree(tmp)
            raise
        return snapshot

    def get(self, snapshot_id: str) -> WebSnapshot | None:
        directory = self.root / snapshot_id
        meta_path = directory / "meta.json"
        body_path = directory / "body.bin"
        if not meta_path.is_file() or not body_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        body = body_path.read_bytes()
        return _snapshot_from_disk(meta, body)

    def get_by_url_and_hash(self, canonical_url: str, content_hash: str) -> WebSnapshot | None:
        return self.get(snapshot_id_for(canonical_url=canonical_url, content_hash=content_hash))

    def latest_for(
        self,
        canonical_url: str,
        *,
        acquisition_mode: str | None = ACQUISITION_STATIC_HTTP,
    ) -> WebSnapshot | None:
        matches: list[WebSnapshot] = []
        for meta_path in self.root.glob("snap_*/meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("canonical_url") != canonical_url:
                continue
            body_path = meta_path.with_name("body.bin")
            if not body_path.is_file():
                continue
            snapshot = _snapshot_from_disk(meta, body_path.read_bytes())
            if acquisition_mode is not None and snapshot.acquisition_mode != acquisition_mode:
                continue
            matches.append(snapshot)
        if not matches:
            return None
        return max(matches, key=lambda item: (item.retrieved_at, item.snapshot_id))

    def list_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.name for path in self.root.iterdir() if path.is_dir() and path.name.startswith("snap_")
            )
        )

    def storage_stats(self) -> SnapshotStorageStats:
        entries = self._snapshot_entries()
        temporary_count = sum(
            1 for path in self.root.iterdir() if path.is_dir() and path.name.startswith(".tmp-")
        )
        return SnapshotStorageStats(
            snapshot_count=len(entries),
            body_bytes=sum(body.stat().st_size for _, _, body, _, _ in entries),
            metadata_bytes=sum(meta.stat().st_size for _, _, _, meta, _ in entries),
            total_bytes=sum(size for _, _, _, _, size in entries),
            temporary_directory_count=temporary_count,
        )

    def garbage_collect(
        self,
        *,
        referenced_ids: Collection[str] = (),
        retention_days: int = 30,
        max_bytes: int | None = None,
        now: datetime | None = None,
        temporary_ttl_seconds: int = 3_600,
    ) -> SnapshotGcResult:
        if retention_days < 0:
            raise ValueError("snapshot retention_days must be non-negative")
        if max_bytes is not None and max_bytes < 0:
            raise ValueError("snapshot max_bytes must be non-negative")
        if temporary_ttl_seconds < 0:
            raise ValueError("temporary_ttl_seconds must be non-negative")
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(days=retention_days)
        references = {str(snapshot_id) for snapshot_id in referenced_ids}
        entries = self._snapshot_entries()
        bytes_before = sum(size for _, _, _, _, size in entries)
        bytes_after = bytes_before
        deleted: list[str] = []
        retained_references: list[str] = []
        for directory, metadata, _, _, size in sorted(
            entries,
            key=lambda item: (_snapshot_datetime(item[1].get("retrieved_at")), item[0].name),
        ):
            retrieved_at = _snapshot_datetime(metadata.get("retrieved_at"))
            expired = retrieved_at < cutoff
            over_capacity = max_bytes is not None and bytes_after > max_bytes
            if not expired and not over_capacity:
                continue
            if directory.name in references:
                retained_references.append(directory.name)
                continue
            _rmtree(directory)
            deleted.append(directory.name)
            bytes_after -= size

        temporary_removed = 0
        temporary_cutoff = current.timestamp() - temporary_ttl_seconds
        for path in self.root.iterdir():
            if not path.is_dir() or not path.name.startswith(".tmp-"):
                continue
            try:
                stale = path.stat().st_mtime <= temporary_cutoff
            except OSError:
                continue
            if stale:
                _rmtree(path)
                temporary_removed += 1
        return SnapshotGcResult(
            scanned_count=len(entries),
            deleted_ids=tuple(sorted(deleted)),
            retained_referenced_ids=tuple(sorted(retained_references)),
            temporary_directories_removed=temporary_removed,
            bytes_before=bytes_before,
            bytes_after=bytes_after,
        )

    def _snapshot_entries(self) -> list[tuple[Path, dict[str, Any], Path, Path, int]]:
        entries: list[tuple[Path, dict[str, Any], Path, Path, int]] = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or not directory.name.startswith(SNAPSHOT_ID_PREFIX):
                continue
            body_path = directory / "body.bin"
            meta_path = directory / "meta.json"
            if not body_path.is_file() or not meta_path.is_file():
                continue
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                size = body_path.stat().st_size + meta_path.stat().st_size
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(metadata, dict):
                continue
            entries.append((directory, metadata, body_path, meta_path, size))
        return entries


def referenced_snapshot_ids(database: Database) -> frozenset[str]:
    """Return snapshot IDs still referenced by immutable Web observations."""
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT payload_json
            FROM observations
            WHERE source_type = ?
            """,
            (WEB_SNAPSHOT_SOURCE_TYPE,),
        ).fetchall()
    referenced: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    isinstance(key, str)
                    and key.endswith("snapshot_id")
                    and isinstance(item, str)
                    and item.startswith(SNAPSHOT_ID_PREFIX)
                ):
                    referenced.add(item)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for row in rows:
        try:
            collect(json.loads(row["payload_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
    return frozenset(referenced)


async def fetch_web_snapshot(
    settings: Settings,
    url: str,
    *,
    store: SnapshotStore,
    retrieved_at: str | None = None,
    previous: WebSnapshot | None = None,
    allow_http: bool = False,
    check_robots: bool = True,
    user_agent: str | None = None,
) -> WebSnapshot:
    """Safely fetch an allowlisted public page and persist an immutable snapshot.

    Does not write Observations and does not treat HTML as Claim evidence.
    This path is static HTTP only. Bounded JS rendering lives in
    ``web_render.maybe_render_web_snapshot`` and is opt-in (#64).
    """
    if not settings.web_hosts:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Web fetching is disabled")
    user_agent = user_agent or settings.crawler_user_agent
    validated = validate_web_url(url, settings.web_hosts, allow_http=allow_http)
    stamp = retrieved_at or _utc_now()
    robots = (
        await _robots_decision(
            settings,
            validated,
            retrieved_at=stamp,
            allow_http=allow_http,
            user_agent=user_agent,
            allowed_hosts=settings.web_hosts,
        )
        if check_robots
        else RobotsDecision(
            source_url=validated,
            robots_url=None,
            allowed=True,
            reason="robots_unchecked",
            retrieved_at=stamp,
        )
    )
    if not robots.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Web fetch is disallowed by robots/crawl policy",
        )

    canonical = canonicalize_url(validated)
    prior = previous or store.latest_for(canonical)
    downloaded = await _download_web_page(
        settings,
        validated,
        previous=prior,
        allow_http=allow_http,
        user_agent=user_agent,
        allowed_hosts=settings.web_hosts,
    )
    if downloaded.status_code == 304:
        if prior is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Web source returned 304 without a stored snapshot",
            )
        return WebSnapshot(
            snapshot_id=prior.snapshot_id,
            canonical_url=prior.canonical_url,
            retrieved_at=prior.retrieved_at,
            content_hash=prior.content_hash,
            status_code=prior.status_code,
            headers=prior.headers,
            body=prior.body,
            etag=prior.etag,
            last_modified=prior.last_modified,
            robots=prior.robots,
            final_url=prior.final_url,
            not_modified=True,
        )

    digest = content_hash_for(downloaded.body)
    existing = store.get_by_url_and_hash(canonical, digest)
    if existing is not None:
        return existing

    snapshot = WebSnapshot(
        snapshot_id=snapshot_id_for(
            canonical_url=canonical,
            content_hash=digest,
            retrieved_at=stamp,
        ),
        canonical_url=canonical,
        retrieved_at=stamp,
        content_hash=digest,
        status_code=downloaded.status_code,
        headers=downloaded.headers,
        body=downloaded.body,
        etag=downloaded.etag,
        last_modified=downloaded.last_modified,
        robots=robots,
        final_url=canonicalize_url(downloaded.final_url),
    )
    return store.put(snapshot)


async def fetch_html_page(
    settings: Settings,
    url: str,
    *,
    allowed_hosts: set[str] | None = None,
    allow_http: bool = False,
    check_robots: bool = True,
    user_agent: str | None = None,
) -> tuple[bytes, str, RobotsDecision]:
    """Fetch HTML for discovery. Does not persist snapshots or Observations."""
    hosts = settings.web_hosts if allowed_hosts is None else allowed_hosts
    if not hosts:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Web fetching is disabled")
    user_agent = user_agent or settings.crawler_user_agent
    validated = validate_web_url(url, hosts, allow_http=allow_http)
    stamp = _utc_now()
    robots = (
        await _robots_decision(
            settings,
            validated,
            retrieved_at=stamp,
            allow_http=allow_http,
            user_agent=user_agent,
            allowed_hosts=hosts,
        )
        if check_robots
        else RobotsDecision(
            source_url=validated,
            robots_url=None,
            allowed=True,
            reason="robots_unchecked",
            retrieved_at=stamp,
        )
    )
    if not robots.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Web fetch is disallowed by robots/crawl policy",
        )
    downloaded = await _download_web_page(
        settings,
        validated,
        previous=None,
        allow_http=allow_http,
        user_agent=user_agent,
        allowed_hosts=hosts,
    )
    return downloaded.body, canonicalize_url(downloaded.final_url), robots


async def evaluate_robots(
    settings: Settings,
    url: str,
    *,
    allowed_hosts: set[str] | None = None,
    allow_http: bool = False,
    user_agent: str | None = None,
) -> RobotsDecision:
    """Robots decision for a URL. Does not persist anything."""
    hosts = settings.web_hosts if allowed_hosts is None else allowed_hosts
    user_agent = user_agent or settings.crawler_user_agent
    validated = validate_web_url(url, hosts, allow_http=allow_http)
    return await _robots_decision(
        settings,
        validated,
        retrieved_at=_utc_now(),
        allow_http=allow_http,
        user_agent=user_agent,
        allowed_hosts=hosts,
    )


@dataclass(frozen=True)
class _DownloadedPage:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    etag: str | None
    last_modified: str | None
    final_url: str


async def _download_web_page(
    settings: Settings,
    url: str,
    *,
    previous: WebSnapshot | None,
    allow_http: bool,
    user_agent: str,
    allowed_hosts: set[str] | None = None,
) -> _DownloadedPage:
    hosts = settings.web_hosts if allowed_hosts is None else allowed_hosts
    current_url = validate_web_url(url, hosts, allow_http=allow_http)
    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "identity",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
    }
    if previous is not None:
        if previous.etag:
            headers["If-None-Match"] = previous.etag
        if previous.last_modified:
            headers["If-Modified-Since"] = previous.last_modified
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            for _ in range(MAX_REDIRECT_ATTEMPTS):
                async with client.stream(
                    "GET",
                    current_url,
                    follow_redirects=False,
                    headers=headers,
                ) as response:
                    require_global_response_peer(response, source_name="Web")
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(
                                status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="Web redirect is invalid",
                            )
                        current_url = validate_web_url(
                            urljoin(current_url, location),
                            hosts,
                            allow_http=allow_http,
                        )
                        continue
                    if response.status_code == 304:
                        return _DownloadedPage(
                            status_code=304,
                            headers=_frozen_headers(response.headers),
                            body=b"",
                            etag=_header(response.headers, "etag"),
                            last_modified=_header(response.headers, "last-modified"),
                            final_url=current_url,
                        )
                    if response.status_code >= 400:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Web source returned HTTP {response.status_code}",
                        )
                    _reject_unsafe_encoding(response.headers)
                    _require_allowed_content_type(response.headers)
                    body = await _bounded_body(response, settings.max_response_bytes, source_name="Web")
                    return _DownloadedPage(
                        status_code=response.status_code,
                        headers=_frozen_headers(response.headers),
                        body=body,
                        etag=_header(response.headers, "etag"),
                        last_modified=_header(response.headers, "last-modified"),
                        final_url=current_url,
                    )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Web source request timed out",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Web source redirected too many times",
    )


async def _robots_decision(
    settings: Settings,
    page_url: str,
    *,
    retrieved_at: str,
    allow_http: bool,
    user_agent: str,
    allowed_hosts: set[str] | None = None,
) -> RobotsDecision:
    hosts = settings.web_hosts if allowed_hosts is None else allowed_hosts
    parsed = urlparse(page_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        validate_web_url(robots_url, hosts, allow_http=allow_http)
    except HTTPException:
        return RobotsDecision(
            source_url=page_url,
            robots_url=robots_url,
            allowed=False,
            reason="robots_url_rejected",
            retrieved_at=retrieved_at,
        )
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream(
                "GET",
                robots_url,
                follow_redirects=False,
                headers={
                    "User-Agent": user_agent,
                    "Accept-Encoding": "identity",
                },
            ) as response:
                require_global_response_peer(response, source_name="Web")
                if response.status_code in {404, 410}:
                    return RobotsDecision(
                        source_url=page_url,
                        robots_url=robots_url,
                        allowed=True,
                        reason="robots_missing",
                        retrieved_at=retrieved_at,
                    )
                if response.status_code != 200:
                    return RobotsDecision(
                        source_url=page_url,
                        robots_url=robots_url,
                        allowed=False,
                        reason=f"robots_http_{response.status_code}",
                        retrieved_at=retrieved_at,
                    )
                body = await _bounded_body(response, ROBOTS_MAX_BYTES, source_name="Web")
    except HTTPException:
        raise
    except httpx.TimeoutException:
        return RobotsDecision(
            source_url=page_url,
            robots_url=robots_url,
            allowed=False,
            reason="robots_timeout",
            retrieved_at=retrieved_at,
        )
    except httpx.HTTPError:
        return RobotsDecision(
            source_url=page_url,
            robots_url=robots_url,
            allowed=False,
            reason="robots_fetch_failed",
            retrieved_at=retrieved_at,
        )
    parser = RobotFileParser()
    parser.parse(body.decode("utf-8", errors="replace").splitlines())
    allowed = bool(parser.can_fetch(user_agent, page_url))
    return RobotsDecision(
        source_url=page_url,
        robots_url=robots_url,
        allowed=allowed,
        reason="robots_allows" if allowed else "robots_disallows",
        retrieved_at=retrieved_at,
    )


async def _bounded_body(response: httpx.Response, limit: int, *, source_name: str) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_raw():
        if len(body) + len(chunk) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{source_name} response exceeded the configured limit",
            )
        body.extend(chunk)
    return bytes(body)


def _require_allowed_content_type(headers: Any) -> None:
    content_type = str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_WEB_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Web content type is not allowed: {content_type or 'missing'}",
        )


def _reject_unsafe_encoding(headers: Any) -> None:
    content_encoding = str(headers.get("content-encoding", "identity")).strip().lower()
    if content_encoding not in {"", "identity"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Compressed Web responses are not allowed",
        )


def _frozen_headers(headers: Any) -> tuple[tuple[str, str], ...]:
    items = [(str(key).lower(), str(value)) for key, value in headers.items()]
    return tuple(sorted(items, key=lambda item: item[0]))


def _header(headers: Any, name: str) -> str | None:
    value = headers.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _encode_meta(snapshot: WebSnapshot) -> str:
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "canonical_url": snapshot.canonical_url,
        "retrieved_at": snapshot.retrieved_at,
        "content_hash": snapshot.content_hash,
        "status_code": snapshot.status_code,
        "headers": list(snapshot.headers),
        "etag": snapshot.etag,
        "last_modified": snapshot.last_modified,
        "robots": {
            "source_url": snapshot.robots.source_url,
            "robots_url": snapshot.robots.robots_url,
            "allowed": snapshot.robots.allowed,
            "reason": snapshot.robots.reason,
            "retrieved_at": snapshot.robots.retrieved_at,
        },
        "final_url": snapshot.final_url,
        "acquisition_mode": snapshot.acquisition_mode,
        "parent_http_snapshot_id": snapshot.parent_http_snapshot_id,
        "renderer_id": snapshot.renderer_id,
        "wait_condition": snapshot.wait_condition,
        "render_reason": snapshot.render_reason,
    }
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _snapshot_from_disk(meta: dict[str, Any], body: bytes) -> WebSnapshot:
    robots_raw = meta["robots"]
    headers = tuple((str(key), str(value)) for key, value in meta["headers"])
    return WebSnapshot(
        snapshot_id=str(meta["snapshot_id"]),
        canonical_url=str(meta["canonical_url"]),
        retrieved_at=str(meta["retrieved_at"]),
        content_hash=str(meta["content_hash"]),
        status_code=int(meta["status_code"]),
        headers=headers,
        body=body,
        etag=meta.get("etag"),
        last_modified=meta.get("last_modified"),
        robots=RobotsDecision(
            source_url=str(robots_raw["source_url"]),
            robots_url=robots_raw.get("robots_url"),
            allowed=bool(robots_raw["allowed"]),
            reason=str(robots_raw["reason"]),
            retrieved_at=robots_raw.get("retrieved_at"),
        ),
        final_url=str(meta["final_url"]),
        acquisition_mode=str(meta.get("acquisition_mode") or ACQUISITION_STATIC_HTTP),
        parent_http_snapshot_id=meta.get("parent_http_snapshot_id"),
        renderer_id=meta.get("renderer_id"),
        wait_condition=meta.get("wait_condition"),
        render_reason=meta.get("render_reason"),
    )


def _snapshots_equivalent(left: WebSnapshot, right: WebSnapshot) -> bool:
    return (
        left.snapshot_id == right.snapshot_id
        and left.canonical_url == right.canonical_url
        and left.content_hash == right.content_hash
        and left.body == right.body
        and left.headers == right.headers
        and left.status_code == right.status_code
        and left.etag == right.etag
        and left.last_modified == right.last_modified
        and left.final_url == right.final_url
        and left.robots == right.robots
        and left.retrieved_at == right.retrieved_at
        and left.acquisition_mode == right.acquisition_mode
        and left.parent_http_snapshot_id == right.parent_http_snapshot_id
        and left.renderer_id == right.renderer_id
        and left.wait_condition == right.wait_condition
        and left.render_reason == right.render_reason
    )


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file():
        path.unlink()
        return
    for child in path.iterdir():
        _rmtree(child)
    path.rmdir()


def _snapshot_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        return datetime.max.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
