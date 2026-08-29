"""Bounded dynamic-Web rendering contract (#64 / Source-08).

This module is the insert boundary for a future isolated renderer. It does
not close #64: a real browser is not implemented here. Start a real renderer
only when ``evaluate_real_renderer_gate`` says so, as an isolated service.

Static HTTP remains the default. JavaScript rendering runs only when all of
the following hold:

1. ``BULLETFEED_DYNAMIC_WEB_ENABLED`` is true
2. the page host is in both ``web_hosts`` and ``dynamic_web_hosts``
3. the source policy is ``bounded_js_when_needed``
4. static #61 normalization is insufficient

The renderer engine is injected. Production default is a null engine that
fail-closes. Tests inject a scripted engine. This module never starts a
browser process. Android WebView JavaScript stays disabled.

Cookies, login, and private browsing are out of scope.
Renderer failure does not create authority and does not mutate the HTTP snapshot.
Rendered bytes go through the same ``normalize_web_snapshot`` path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from fastapi import HTTPException, status

from app.config import Settings
from app.services.url_safety import validate_public_url
from app.services.web_normalize import normalize_web_snapshot
from app.services.web_snapshots import (
    ACQUISITION_BOUNDED_JS,
    DEFAULT_USER_AGENT,
    SnapshotStore,
    WebSnapshot,
    content_hash_for,
    fetch_web_snapshot,
    snapshot_id_for,
)

RENDER_POLICY_STATIC_ONLY = "static_only"
RENDER_POLICY_BOUNDED_JS = "bounded_js_when_needed"
WAIT_DOMCONTENTLOADED = "domcontentloaded"
WAIT_NETWORKIDLE = "networkidle"
WAIT_SELECTOR = "selector"
WAIT_CONDITIONS = frozenset({WAIT_DOMCONTENTLOADED, WAIT_NETWORKIDLE, WAIT_SELECTOR})
RENDER_SOURCE_NAME = "WebRender"
RENDERED_CONTENT_TYPE = "text/html; charset=utf-8"

REASON_STATIC_ONLY = "static_only_policy"
REASON_DISABLED = "disabled"
REASON_HOST_NOT_ALLOWLISTED = "host_not_allowlisted"
REASON_STATIC_SUFFICIENT = "static_sufficient"
REASON_RENDERED = "rendered"
REASON_TIMEOUT = "timeout"
REASON_CRASH = "crash"
REASON_RUNAWAY = "runaway_requests"
REASON_BLOCKED_PRIVATE = "blocked_private"
REASON_SSRF = "ssrf"
REASON_OUTPUT_TOO_LARGE = "output_too_large"
REASON_MEMORY = "memory_limit"
REASON_UNAVAILABLE = "renderer_unavailable"
REASON_WAIT_UNSATISFIED = "wait_unsatisfied"
REASON_COOKIES = "cookies_out_of_scope"
REASON_UNSAFE_FINAL_URL = "unsafe_final_url"

AuthorizeSubresource = Callable[[str], Awaitable[str]]


class RenderFailure(Exception):
    """Fail-closed renderer outcome. Never treated as source authority."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class RenderLimits:
    timeout_seconds: float
    max_output_bytes: int
    max_subresources: int
    max_memory_mb: int


@dataclass(frozen=True)
class RenderPolicy:
    mode: str = RENDER_POLICY_STATIC_ONLY
    wait_until: str = WAIT_DOMCONTENTLOADED
    wait_selector: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {RENDER_POLICY_STATIC_ONLY, RENDER_POLICY_BOUNDED_JS}:
            raise ValueError(f"unknown render policy mode: {self.mode}")
        if self.wait_until not in WAIT_CONDITIONS:
            raise ValueError(f"unknown wait condition: {self.wait_until}")
        if self.wait_until == WAIT_SELECTOR and not self.wait_selector:
            raise ValueError("selector wait requires wait_selector")


@dataclass(frozen=True)
class RenderRequest:
    url: str
    http_snapshot: WebSnapshot
    wait_until: str
    wait_selector: str | None
    allowed_hosts: set[str]
    allow_http: bool
    limits: RenderLimits


@dataclass(frozen=True)
class RenderedDocument:
    body: bytes
    final_url: str
    wait_condition: str
    subresource_urls: tuple[str, ...] = ()
    memory_mb: float = 0.0
    cookies_used: bool = False
    wait_satisfied: bool = True


@dataclass(frozen=True)
class RenderAttempt:
    used: bool
    reason: str
    snapshot: WebSnapshot
    http_snapshot: WebSnapshot


class RendererEngine(Protocol):
    renderer_id: str

    async def render(
        self,
        request: RenderRequest,
        authorize: AuthorizeSubresource,
    ) -> RenderedDocument: ...


class NullRenderer:
    """Production default. Never executes JavaScript."""

    renderer_id = "null-v1"

    async def render(
        self,
        request: RenderRequest,
        authorize: AuthorizeSubresource,
    ) -> RenderedDocument:
        del request, authorize
        raise RenderFailure(REASON_UNAVAILABLE, "no renderer engine is configured")


@dataclass(frozen=True)
class ScriptedPage:
    """Deterministic fixture used by tests. Not a browser."""

    body: bytes
    extra_requests: tuple[str, ...] = ()
    delay_seconds: float = 0.0
    crash: bool = False
    memory_mb: float = 1.0
    wait_satisfied: bool = True
    cookies_used: bool = False
    final_url: str | None = None


class ScriptedRenderer:
    """In-process renderer for tests. Honors documented wait conditions."""

    renderer_id = "scripted-test-v1"

    def __init__(self, pages: dict[str, ScriptedPage]) -> None:
        self.pages = pages

    async def render(
        self,
        request: RenderRequest,
        authorize: AuthorizeSubresource,
    ) -> RenderedDocument:
        page = self.pages.get(request.url)
        if page is None:
            raise RenderFailure(REASON_UNAVAILABLE, f"no scripted page for {request.url}")
        if page.crash:
            raise RenderFailure(REASON_CRASH, "scripted renderer crashed")
        if page.delay_seconds > request.limits.timeout_seconds:
            raise RenderFailure(REASON_TIMEOUT, "scripted renderer exceeded the time limit")
        if not page.wait_satisfied:
            raise RenderFailure(
                REASON_WAIT_UNSATISFIED,
                f"wait condition {request.wait_until} was not met",
            )
        validated: list[str] = [await authorize(request.url)]
        for extra in page.extra_requests:
            validated.append(await authorize(extra))
        return RenderedDocument(
            body=page.body,
            final_url=page.final_url or request.url,
            wait_condition=request.wait_until,
            subresource_urls=tuple(validated),
            memory_mb=page.memory_mb,
            cookies_used=page.cookies_used,
            wait_satisfied=page.wait_satisfied,
        )


def render_limits_from_settings(settings: Settings) -> RenderLimits:
    return RenderLimits(
        timeout_seconds=float(settings.dynamic_web_timeout_seconds),
        max_output_bytes=int(settings.dynamic_web_max_output_bytes),
        max_subresources=int(settings.dynamic_web_max_subresources),
        max_memory_mb=int(settings.dynamic_web_max_memory_mb),
    )


def static_extraction_is_insufficient(snapshot: WebSnapshot) -> bool:
    """Need detector: reuse #61. Rejected/empty documents are JS-shell gaps."""
    return bool(normalize_web_snapshot(snapshot).rejected)


def render_host_is_allowlisted(url: str, settings: Settings) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        return False
    allowed = settings.web_hosts & settings.dynamic_web_hosts
    return any(host == item or host.endswith(f".{item}") for item in allowed)


async def authorize_render_url(
    url: str,
    settings: Settings,
    *,
    allow_http: bool = False,
    seen: list[str] | None = None,
    limits: RenderLimits | None = None,
) -> str:
    """SSRF + allowlist + runaway guard for the document and every subresource."""
    allowed = settings.web_hosts & settings.dynamic_web_hosts
    if not allowed:
        raise RenderFailure(REASON_HOST_NOT_ALLOWLISTED, "dynamic Web host allowlist is empty")
    try:
        validated = validate_public_url(
            url,
            allowed,
            source_name=RENDER_SOURCE_NAME,
            allow_http=allow_http,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN and "private" in str(exc.detail):
            raise RenderFailure(REASON_BLOCKED_PRIVATE, str(exc.detail)) from exc
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            raise RenderFailure(REASON_HOST_NOT_ALLOWLISTED, str(exc.detail)) from exc
        raise RenderFailure(REASON_SSRF, str(exc.detail)) from exc
    bucket = seen if seen is not None else []
    bucket.append(validated)
    cap = limits.max_subresources if limits is not None else settings.dynamic_web_max_subresources
    if len(bucket) > cap:
        raise RenderFailure(REASON_RUNAWAY, "renderer exceeded the subresource request limit")
    return validated


async def acquire_web_snapshot(
    settings: Settings,
    url: str,
    *,
    store: SnapshotStore,
    policy: RenderPolicy | None = None,
    engine: RendererEngine | None = None,
    retrieved_at: str | None = None,
    previous: WebSnapshot | None = None,
    allow_http: bool = False,
    check_robots: bool = True,
    user_agent: str | None = None,
) -> RenderAttempt:
    """Static fetch first, then optional bounded render. Default policy is static-only."""
    http_snapshot = await fetch_web_snapshot(
        settings,
        url,
        store=store,
        retrieved_at=retrieved_at,
        previous=previous,
        allow_http=allow_http,
        check_robots=check_robots,
        user_agent=user_agent or DEFAULT_USER_AGENT,
    )
    return await maybe_render_web_snapshot(
        settings,
        http_snapshot,
        store=store,
        policy=policy or RenderPolicy(),
        engine=engine,
        allow_http=allow_http,
        retrieved_at=retrieved_at,
    )


async def maybe_render_web_snapshot(
    settings: Settings,
    http_snapshot: WebSnapshot,
    *,
    store: SnapshotStore,
    policy: RenderPolicy,
    engine: RendererEngine | None = None,
    allow_http: bool = False,
    retrieved_at: str | None = None,
) -> RenderAttempt:
    """Return a rendered snapshot only when policy + need require it.

    On any renderer failure the original HTTP snapshot is returned unchanged.
    """
    if http_snapshot.is_rendered:
        return RenderAttempt(
            used=False,
            reason=REASON_STATIC_SUFFICIENT,
            snapshot=http_snapshot,
            http_snapshot=http_snapshot,
        )
    if policy.mode != RENDER_POLICY_BOUNDED_JS:
        return RenderAttempt(False, REASON_STATIC_ONLY, http_snapshot, http_snapshot)
    if not settings.dynamic_web_enabled:
        return RenderAttempt(False, REASON_DISABLED, http_snapshot, http_snapshot)
    if not render_host_is_allowlisted(http_snapshot.canonical_url, settings):
        return RenderAttempt(False, REASON_HOST_NOT_ALLOWLISTED, http_snapshot, http_snapshot)
    if not static_extraction_is_insufficient(http_snapshot):
        return RenderAttempt(False, REASON_STATIC_SUFFICIENT, http_snapshot, http_snapshot)

    selected = engine or NullRenderer()
    limits = render_limits_from_settings(settings)
    seen: list[str] = []

    async def authorize(url: str) -> str:
        return await authorize_render_url(
            url,
            settings,
            allow_http=allow_http,
            seen=seen,
            limits=limits,
        )

    request = RenderRequest(
        url=http_snapshot.canonical_url,
        http_snapshot=http_snapshot,
        wait_until=policy.wait_until,
        wait_selector=policy.wait_selector,
        allowed_hosts=settings.web_hosts & settings.dynamic_web_hosts,
        allow_http=allow_http,
        limits=limits,
    )
    try:
        rendered = await selected.render(request, authorize)
        snapshot = _persist_rendered_snapshot(
            http_snapshot,
            rendered,
            store=store,
            renderer_id=selected.renderer_id,
            limits=limits,
            settings=settings,
            allow_http=allow_http,
            retrieved_at=retrieved_at,
        )
    except RenderFailure as exc:
        return RenderAttempt(False, exc.reason, http_snapshot, http_snapshot)
    return RenderAttempt(True, REASON_RENDERED, snapshot, http_snapshot)


def _persist_rendered_snapshot(
    http_snapshot: WebSnapshot,
    rendered: RenderedDocument,
    *,
    store: SnapshotStore,
    renderer_id: str,
    limits: RenderLimits,
    settings: Settings,
    allow_http: bool,
    retrieved_at: str | None,
) -> WebSnapshot:
    if rendered.cookies_used:
        raise RenderFailure(REASON_COOKIES, "cookies and login are out of scope")
    if not rendered.wait_satisfied:
        raise RenderFailure(REASON_WAIT_UNSATISFIED, "documented wait condition was not met")
    if rendered.memory_mb > limits.max_memory_mb:
        raise RenderFailure(REASON_MEMORY, "renderer exceeded the memory limit")
    if len(rendered.body) > limits.max_output_bytes:
        raise RenderFailure(REASON_OUTPUT_TOO_LARGE, "rendered output exceeded the configured limit")
    try:
        final_url = validate_public_url(
            rendered.final_url,
            settings.web_hosts & settings.dynamic_web_hosts,
            source_name=RENDER_SOURCE_NAME,
            allow_http=allow_http,
        )
    except HTTPException as exc:
        raise RenderFailure(REASON_UNSAFE_FINAL_URL, str(exc.detail)) from exc

    digest = content_hash_for(rendered.body)
    stamp = retrieved_at or http_snapshot.retrieved_at
    snapshot = WebSnapshot(
        snapshot_id=snapshot_id_for(
            canonical_url=http_snapshot.canonical_url,
            content_hash=digest,
            retrieved_at=stamp,
            acquisition_mode=ACQUISITION_BOUNDED_JS,
        ),
        canonical_url=http_snapshot.canonical_url,
        retrieved_at=stamp,
        content_hash=digest,
        status_code=http_snapshot.status_code,
        headers=(
            ("content-type", RENDERED_CONTENT_TYPE),
            ("x-bulletfeed-acquisition", ACQUISITION_BOUNDED_JS),
        ),
        body=rendered.body,
        etag=None,
        last_modified=None,
        robots=http_snapshot.robots,
        final_url=final_url,
        acquisition_mode=ACQUISITION_BOUNDED_JS,
        parent_http_snapshot_id=http_snapshot.snapshot_id,
        renderer_id=renderer_id,
        wait_condition=rendered.wait_condition,
        render_reason=REASON_RENDERED,
    )
    return store.put(snapshot)
