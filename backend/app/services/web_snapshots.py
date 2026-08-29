from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.database import Database
from app.services.source_catalog import SourceKind
from app.services.source_registry import canonicalize_url
from app.services.url_safety import require_global_response_peer, validate_public_url

WEB_SNAPSHOT_SOURCE_TYPE = SourceKind.GENERIC_WEB.value
WEB_SNAPSHOT_POLL_INTERVAL_SECONDS = 300
WEB_SNAPSHOT_RETRY_BASE_SECONDS = 30
WEB_SNAPSHOT_RETRY_MAX_SECONDS = 3600
MAX_REDIRECT_ATTEMPTS = 4
DEFAULT_USER_AGENT = "BulletFeed-local-prototype/0.1 (+local development)"
ALLOWED_WEB_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
}
ROBOTS_MAX_BYTES = 64_000
SNAPSHOT_ID_PREFIX = "snap_"


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

    @property
    def header_map(self) -> dict[str, str]:
        return {key: value for key, value in self.headers}


def content_hash_for(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def snapshot_id_for(
    *,
    canonical_url: str,
    content_hash: str,
    retrieved_at: str | None = None,
) -> str:
    """Stable snapshot identity.

    Content-addressed per canonical URL so identical bytes do not fork a
    second version. ``retrieved_at`` is accepted for provenance callers and
    recorded on the snapshot, but it is not part of the identity.
    """
    del retrieved_at
    material = f"{canonical_url}\n{content_hash}"
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
                raise SnapshotImmutabilityError(
                    f"refusing to mutate stored snapshot {snapshot.snapshot_id}"
                )
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

    def latest_for(self, canonical_url: str) -> WebSnapshot | None:
        matches: list[WebSnapshot] = []
        for meta_path in self.root.glob("snap_*/meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("canonical_url") != canonical_url:
                continue
            body_path = meta_path.with_name("body.bin")
            if not body_path.is_file():
                continue
            matches.append(_snapshot_from_disk(meta, body_path.read_bytes()))
        if not matches:
            return None
        return max(matches, key=lambda item: (item.retrieved_at, item.snapshot_id))

    def list_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(path.name for path in self.root.iterdir() if path.is_dir() and path.name.startswith("snap_"))
        )


async def fetch_web_snapshot(
    settings: Settings,
    url: str,
    *,
    store: SnapshotStore,
    retrieved_at: str | None = None,
    previous: WebSnapshot | None = None,
    allow_http: bool = False,
    check_robots: bool = True,
    user_agent: str = DEFAULT_USER_AGENT,
) -> WebSnapshot:
    """Safely fetch an allowlisted public page and persist an immutable snapshot.

    Does not write Observations and does not treat HTML as Claim evidence.
    JavaScript rendering is out of scope (#64).
    """
    if not settings.web_hosts:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Web fetching is disabled")
    validated = validate_web_url(url, settings.web_hosts, allow_http=allow_http)
    stamp = retrieved_at or _utc_now()
    robots = (
        await _robots_decision(
            settings,
            validated,
            retrieved_at=stamp,
            allow_http=allow_http,
            user_agent=user_agent,
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
) -> _DownloadedPage:
    current_url = validate_web_url(url, settings.web_hosts, allow_http=allow_http)
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
                            settings.web_hosts,
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
) -> RobotsDecision:
    parsed = urlparse(page_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        validate_web_url(robots_url, settings.web_hosts, allow_http=allow_http)
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


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
