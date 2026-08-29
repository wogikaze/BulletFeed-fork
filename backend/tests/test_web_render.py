from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Settings
from app.services.web_normalize import normalize_web_snapshot
from app.services.web_render import (
    REASON_BLOCKED_PRIVATE,
    REASON_COOKIES,
    REASON_CRASH,
    REASON_DISABLED,
    REASON_HOST_NOT_ALLOWLISTED,
    REASON_MEMORY,
    REASON_OUTPUT_TOO_LARGE,
    REASON_RENDERED,
    REASON_RUNAWAY,
    REASON_STATIC_ONLY,
    REASON_STATIC_SUFFICIENT,
    REASON_TIMEOUT,
    REASON_UNAVAILABLE,
    REASON_UNSAFE_FINAL_URL,
    REASON_WAIT_UNSATISFIED,
    RENDER_POLICY_BOUNDED_JS,
    WAIT_SELECTOR,
    NullRenderer,
    RenderFailure,
    RenderPolicy,
    ScriptedPage,
    ScriptedRenderer,
    acquire_web_snapshot,
    authorize_render_url,
    maybe_render_web_snapshot,
    static_extraction_is_insufficient,
)
from app.services.web_snapshots import (
    ACQUISITION_BOUNDED_JS,
    ACQUISITION_STATIC_HTTP,
    RobotsDecision,
    SnapshotStore,
    WebSnapshot,
    content_hash_for,
    snapshot_id_for,
)

PUBLIC_PEER = "93.184.216.34"
PAGE_URL = "https://docs.example.com/pricing"
SPA_SHELL = b"<html><body><div id='app'></div><script>boot()</script></body></html>"
RENDERED_PRICING = (
    b"<html><body><main><h1>Pricing</h1><p>Pro plan is $29 per month.</p></main></body></html>"
)
STATIC_CHANGELOG = (
    b"<html><body><main><h1>Changelog</h1><p>Version 2.0 ships tomorrow.</p></main></body></html>"
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "web_allowed_hosts": "docs.example.com",
        "dynamic_web_enabled": True,
        "dynamic_web_allowed_hosts": "docs.example.com",
        "dynamic_web_timeout_seconds": 8.0,
        "dynamic_web_max_output_bytes": 1_048_576,
        "dynamic_web_max_subresources": 8,
        "dynamic_web_max_memory_mb": 128,
    }
    values.update(overrides)
    return Settings(**values)


def _snapshot(
    body: bytes,
    *,
    canonical_url: str = PAGE_URL,
    retrieved_at: str = "2026-08-29T00:00:00Z",
    acquisition_mode: str = ACQUISITION_STATIC_HTTP,
) -> WebSnapshot:
    digest = content_hash_for(body)
    return WebSnapshot(
        snapshot_id=snapshot_id_for(
            canonical_url=canonical_url,
            content_hash=digest,
            retrieved_at=retrieved_at,
            acquisition_mode=acquisition_mode,
        ),
        canonical_url=canonical_url,
        retrieved_at=retrieved_at,
        content_hash=digest,
        status_code=200,
        headers=(("content-type", "text/html"),),
        body=body,
        etag='"v1"',
        last_modified="Wed, 20 Aug 2026 10:00:00 GMT",
        robots=RobotsDecision(
            source_url=canonical_url,
            robots_url="https://docs.example.com/robots.txt",
            allowed=True,
            reason="robots_allows",
            retrieved_at=retrieved_at,
        ),
        final_url=canonical_url,
        acquisition_mode=acquisition_mode,
    )


def _public_dns(peer: str = PUBLIC_PEER):
    return patch(
        "app.services.url_safety.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", (peer, 443))],
    )


def test_static_http_snapshot_ids_do_not_change() -> None:
    body = STATIC_CHANGELOG
    digest = content_hash_for(body)
    assert snapshot_id_for(canonical_url=PAGE_URL, content_hash=digest) == snapshot_id_for(
        canonical_url=PAGE_URL,
        content_hash=digest,
        acquisition_mode=ACQUISITION_STATIC_HTTP,
    )
    rendered_id = snapshot_id_for(
        canonical_url=PAGE_URL,
        content_hash=digest,
        acquisition_mode=ACQUISITION_BOUNDED_JS,
    )
    assert rendered_id != snapshot_id_for(canonical_url=PAGE_URL, content_hash=digest)


def test_legacy_meta_defaults_to_static_http(tmp_path: Path) -> None:
    snapshot = _snapshot(STATIC_CHANGELOG)
    store = SnapshotStore(tmp_path / "snaps")
    store.put(snapshot)
    meta_path = tmp_path / "snaps" / snapshot.snapshot_id / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in (
        "acquisition_mode",
        "parent_http_snapshot_id",
        "renderer_id",
        "wait_condition",
        "render_reason",
    ):
        meta.pop(key, None)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    loaded = store.get(snapshot.snapshot_id)
    assert loaded is not None
    assert loaded.acquisition_mode == ACQUISITION_STATIC_HTTP
    assert loaded.is_rendered is False


@pytest.mark.asyncio
async def test_static_success_does_not_render(tmp_path: Path) -> None:
    http_snapshot = _snapshot(STATIC_CHANGELOG)
    store = SnapshotStore(tmp_path / "snaps")
    store.put(http_snapshot)
    engine = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING)})
    with _public_dns():
        attempt = await maybe_render_web_snapshot(
            _settings(),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=engine,
        )
    assert attempt.used is False
    assert attempt.reason == REASON_STATIC_SUFFICIENT
    assert attempt.snapshot.snapshot_id == http_snapshot.snapshot_id
    assert static_extraction_is_insufficient(http_snapshot) is False


@pytest.mark.asyncio
async def test_disabled_flag_and_static_policy_skip_renderer(tmp_path: Path) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")
    store.put(http_snapshot)
    engine = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING)})
    disabled = await maybe_render_web_snapshot(
        _settings(dynamic_web_enabled=False),
        http_snapshot,
        store=store,
        policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
        engine=engine,
    )
    assert disabled.reason == REASON_DISABLED
    static_only = await maybe_render_web_snapshot(
        _settings(),
        http_snapshot,
        store=store,
        policy=RenderPolicy(),
        engine=engine,
    )
    assert static_only.reason == REASON_STATIC_ONLY


@pytest.mark.asyncio
async def test_js_shell_is_rendered_and_feeds_normalizer(tmp_path: Path) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")
    store.put(http_snapshot)
    assert static_extraction_is_insufficient(http_snapshot) is True
    engine = ScriptedRenderer(
        {
            PAGE_URL: ScriptedPage(
                body=RENDERED_PRICING,
                extra_requests=("https://docs.example.com/app.js",),
            )
        }
    )
    with _public_dns():
        attempt = await maybe_render_web_snapshot(
            _settings(),
            http_snapshot,
            store=store,
            policy=RenderPolicy(
                mode=RENDER_POLICY_BOUNDED_JS,
                wait_until=WAIT_SELECTOR,
                wait_selector="#app",
            ),
            engine=engine,
        )
    assert attempt.used is True
    assert attempt.reason == REASON_RENDERED
    rendered = attempt.snapshot
    assert rendered.is_rendered is True
    assert rendered.parent_http_snapshot_id == http_snapshot.snapshot_id
    assert rendered.renderer_id == "scripted-test-v1"
    assert rendered.wait_condition == WAIT_SELECTOR
    assert rendered.body == RENDERED_PRICING
    assert rendered.content_hash != http_snapshot.content_hash
    assert store.get(http_snapshot.snapshot_id).body == SPA_SHELL
    document = normalize_web_snapshot(rendered)
    assert document.rejected is False
    assert "Pro plan is $29" in " ".join(
        block.text for section in document.sections for block in section.blocks
    )
    assert store.latest_for(PAGE_URL).snapshot_id == http_snapshot.snapshot_id
    latest_rendered = store.latest_for(PAGE_URL, acquisition_mode=ACQUISITION_BOUNDED_JS)
    assert latest_rendered is not None
    assert latest_rendered.snapshot_id == rendered.snapshot_id


@pytest.mark.asyncio
async def test_timeout_crash_and_missing_engine_fail_closed(tmp_path: Path) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")
    store.put(http_snapshot)
    timeout_engine = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING, delay_seconds=30)})
    crash_engine = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING, crash=True)})
    with _public_dns():
        timeout = await maybe_render_web_snapshot(
            _settings(dynamic_web_timeout_seconds=8.0),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=timeout_engine,
        )
        crash = await maybe_render_web_snapshot(
            _settings(),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=crash_engine,
        )
        missing = await maybe_render_web_snapshot(
            _settings(),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=NullRenderer(),
        )
    assert timeout.reason == REASON_TIMEOUT
    assert crash.reason == REASON_CRASH
    assert missing.reason == REASON_UNAVAILABLE
    for attempt in (timeout, crash, missing):
        assert attempt.used is False
        assert attempt.snapshot.snapshot_id == http_snapshot.snapshot_id
        assert store.get(http_snapshot.snapshot_id).body == SPA_SHELL


@pytest.mark.asyncio
async def test_runaway_subresources_fail_closed(tmp_path: Path) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")
    extras = tuple(f"https://docs.example.com/chunk-{index}.js" for index in range(10))
    engine = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING, extra_requests=extras)})
    with _public_dns():
        attempt = await maybe_render_web_snapshot(
            _settings(dynamic_web_max_subresources=8),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=engine,
        )
    assert attempt.used is False
    assert attempt.reason == REASON_RUNAWAY
    assert attempt.snapshot.body == SPA_SHELL


@pytest.mark.asyncio
async def test_private_subresource_is_blocked(tmp_path: Path) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")
    engine = ScriptedRenderer(
        {
            PAGE_URL: ScriptedPage(
                body=RENDERED_PRICING,
                extra_requests=("https://docs.example.com/internal",),
            )
        }
    )

    def _dns(host: str, port: int, *args, **kwargs):
        del host, args, kwargs
        peer = PUBLIC_PEER if _dns.calls == 0 else "10.0.0.8"  # type: ignore[attr-defined]
        _dns.calls += 1  # type: ignore[attr-defined]
        return [(2, 1, 6, "", (peer, port))]

    _dns.calls = 0  # type: ignore[attr-defined]
    with patch("app.services.url_safety.socket.getaddrinfo", side_effect=_dns):
        attempt = await maybe_render_web_snapshot(
            _settings(),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=engine,
        )
    assert attempt.reason == REASON_BLOCKED_PRIVATE
    assert attempt.used is False


@pytest.mark.asyncio
async def test_authorize_rejects_unknown_host_and_loopback() -> None:
    settings = _settings()
    with pytest.raises(RenderFailure) as unknown:
        await authorize_render_url("https://attacker.example/page", settings)
    assert unknown.value.reason == REASON_HOST_NOT_ALLOWLISTED
    with patch(
        "app.services.url_safety.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
    ):
        with pytest.raises(RenderFailure) as loopback:
            await authorize_render_url("https://docs.example.com/page", settings)
    assert loopback.value.reason == REASON_BLOCKED_PRIVATE


@pytest.mark.asyncio
async def test_cookies_memory_and_unsatisfied_wait_fail_closed(tmp_path: Path) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")
    cookies = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING, cookies_used=True)})
    memory = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING, memory_mb=512)})
    wait = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING, wait_satisfied=False)})
    with _public_dns():
        cookie_attempt = await maybe_render_web_snapshot(
            _settings(),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=cookies,
        )
        memory_attempt = await maybe_render_web_snapshot(
            _settings(dynamic_web_max_memory_mb=128),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=memory,
        )
        wait_attempt = await maybe_render_web_snapshot(
            _settings(),
            http_snapshot,
            store=store,
            policy=RenderPolicy(
                mode=RENDER_POLICY_BOUNDED_JS,
                wait_until=WAIT_SELECTOR,
                wait_selector="main",
            ),
            engine=wait,
        )
    assert cookie_attempt.reason == REASON_COOKIES
    assert memory_attempt.reason == REASON_MEMORY
    assert wait_attempt.reason == REASON_WAIT_UNSATISFIED


def test_selector_wait_requires_selector() -> None:
    with pytest.raises(ValueError, match="wait_selector"):
        RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS, wait_until=WAIT_SELECTOR)


@pytest.mark.asyncio
async def test_host_outside_dynamic_allowlist_is_not_rendered(tmp_path: Path) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")
    engine = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING)})
    attempt = await maybe_render_web_snapshot(
        _settings(dynamic_web_allowed_hosts="other.example"),
        http_snapshot,
        store=store,
        policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
        engine=engine,
    )
    assert attempt.reason == REASON_HOST_NOT_ALLOWLISTED
    assert attempt.used is False


@pytest.mark.asyncio
async def test_oversized_output_and_private_final_url_fail_closed(tmp_path: Path) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")
    huge = ScriptedRenderer({PAGE_URL: ScriptedPage(body=b"<main>x</main>" * 200)})
    redirected = ScriptedRenderer(
        {PAGE_URL: ScriptedPage(body=RENDERED_PRICING, final_url="https://attacker.example/page")}
    )
    with _public_dns():
        oversized = await maybe_render_web_snapshot(
            _settings(dynamic_web_max_output_bytes=64),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=huge,
        )
        unsafe = await maybe_render_web_snapshot(
            _settings(),
            http_snapshot,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=redirected,
        )
    assert oversized.reason == REASON_OUTPUT_TOO_LARGE
    assert unsafe.reason == REASON_UNSAFE_FINAL_URL
    assert oversized.used is False
    assert unsafe.used is False


@pytest.mark.asyncio
async def test_acquire_defaults_to_static_only(tmp_path: Path, monkeypatch) -> None:
    http_snapshot = _snapshot(SPA_SHELL)
    store = SnapshotStore(tmp_path / "snaps")

    async def _fake_fetch(*args, **kwargs):
        del args, kwargs
        return http_snapshot

    monkeypatch.setattr("app.services.web_render.fetch_web_snapshot", _fake_fetch)
    engine = ScriptedRenderer({PAGE_URL: ScriptedPage(body=RENDERED_PRICING)})
    attempt = await acquire_web_snapshot(
        _settings(),
        PAGE_URL,
        store=store,
        engine=engine,
    )
    assert attempt.reason == REASON_STATIC_ONLY
    assert attempt.used is False
    with _public_dns():
        rendered = await acquire_web_snapshot(
            _settings(),
            PAGE_URL,
            store=store,
            policy=RenderPolicy(mode=RENDER_POLICY_BOUNDED_JS),
            engine=engine,
        )
    assert rendered.used is True
    assert rendered.reason == REASON_RENDERED
