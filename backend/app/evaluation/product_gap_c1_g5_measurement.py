"""Dev-only G5 measurement: SSRF shape plus production fetch and redirect identity.

Does not invent a pass. Live fetch failures stay unmeasured. This path does not
write Observations, Claims, or subscriptions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from app.config import Settings
from app.evaluation.product_gap_ssrf import evaluate_ssrf_suite
from app.services.rss import preview_feed
from app.services.source_registry import canonicalize_url

_FETCH_URL = "https://react.dev/rss.xml"
_IDENTITY_URL = "https://www.mongodb.com/products/updates/rss"


def _host(url: str) -> str | None:
    try:
        canonical = canonicalize_url(url)
    except ValueError:
        canonical = url
    host = (urlparse(canonical).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _same_public_source(start: str, final: str) -> bool:
    left = _host(start)
    right = _host(final)
    return bool(left and right and left == right)


async def measure_live_g5(
    gold_dir: Path,
    *,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    ssrf_path = gold_dir.parent / "ssrf_adversarial.json"
    ssrf = evaluate_ssrf_suite(ssrf_path)
    settings = Settings(request_timeout_seconds=timeout_seconds)
    retrieved_at = datetime.now(UTC).isoformat()

    fetch_row: dict[str, Any]
    try:
        preview = await preview_feed(settings, _FETCH_URL)
        items = preview.get("items") if isinstance(preview.get("items"), list) else []
        fetch_row = {
            "url": _FETCH_URL,
            "status": "ok",
            "final_url": preview.get("source_url"),
            "item_count": len(items),
        }
        production_fetch_measured = len(items) > 0
    except HTTPException as exc:
        fetch_row = {
            "url": _FETCH_URL,
            "status": "failed",
            "http_status": exc.status_code,
            "detail": str(exc.detail),
        }
        production_fetch_measured = False
    except Exception as exc:  # noqa: BLE001 - live failures stay visible
        fetch_row = {
            "url": _FETCH_URL,
            "status": "failed",
            "exception_type": type(exc).__name__,
            "detail": str(exc),
        }
        production_fetch_measured = False

    identity_row: dict[str, Any]
    try:
        preview = await preview_feed(settings, _IDENTITY_URL)
        final_url = str(preview.get("source_url") or "")
        same = _same_public_source(_IDENTITY_URL, final_url)
        identity_row = {
            "start_url": _IDENTITY_URL,
            "final_url": final_url,
            "same_public_source": same,
            "status": "ok",
        }
        identity_measured = same
    except HTTPException as exc:
        identity_row = {
            "start_url": _IDENTITY_URL,
            "status": "failed",
            "http_status": exc.status_code,
            "detail": str(exc.detail),
        }
        identity_measured = False
    except Exception as exc:  # noqa: BLE001
        identity_row = {
            "start_url": _IDENTITY_URL,
            "status": "failed",
            "exception_type": type(exc).__name__,
            "detail": str(exc),
        }
        identity_measured = False

    return {
        "artifact_version": "product-gap-c1-g5-measurement-v1",
        "path": "production_rss_fetch_and_redirect_identity",
        "split": "dev",
        "retrieved_at": retrieved_at,
        "production_fetch_measured": production_fetch_measured,
        "identity_measured": identity_measured,
        "shape_bypass_count": int(ssrf.get("shape_bypass_count") or 0),
        "ssrf": {
            "suite_version": ssrf.get("suite_version"),
            "case_count": ssrf.get("case_count"),
            "shape_bypass_count": ssrf.get("shape_bypass_count"),
            "bypasses": ssrf.get("bypasses"),
            "production_path": ssrf.get("production_path"),
        },
        "production_fetch": fetch_row,
        "redirect_identity": identity_row,
    }
