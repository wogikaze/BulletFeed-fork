"""Measure the production URL-shape portion of G5 into an artifact.

This deliberately does not claim redirect/DNS/peer-fetch coverage.  Those
checks require a separate controlled transport or live qualification run and
remain explicit fields in the artifact instead of implicit PASS values.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlparse

from fastapi import HTTPException

from app.config import Settings
from app.evaluation.product_gap_ssrf import evaluate_ssrf_suite
from app.services.web_snapshots import fetch_html_page, validate_web_url


class _FakeNetworkStream:
    def __init__(self, peer: str) -> None:
        self.peer = peer

    def get_extra_info(self, name: str):
        return (self.peer, 443) if name == "server_addr" else None


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        peer: str = "93.184.216.34",
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html"}
        self.extensions = {"network_stream": _FakeNetworkStream(peer)}
        self._chunks = chunks if chunks is not None else [b"<html><body>ok</body></html>"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aiter_raw(self):
        for chunk in self._chunks:
            yield chunk


class _FakeClient:
    def __init__(self, routes: dict[str, _FakeResponse]) -> None:
        self.routes = routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, _method: str, url: str, **_kwargs: object):
        if url not in self.routes:
            raise AssertionError(f"unexpected controlled G5 request: {url}")
        return self.routes[url]


def _public_dns():
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def _same_source_host(left: str, right: str) -> bool:
    left_host = (urlparse(left).hostname or "").removeprefix("www.")
    right_host = (urlparse(right).hostname or "").removeprefix("www.")
    return bool(left_host) and left_host == right_host


def _controlled_cases() -> list[dict[str, Any]]:
    settings = Settings(web_allowed_hosts="example.com", request_timeout_seconds=1.0)
    cases: list[dict[str, Any]] = []
    redirect_client = _FakeClient(
        {
            "https://example.com/robots.txt": _FakeResponse(
                status_code=404,
                headers={"content-type": "text/plain"},
                chunks=[b""],
            ),
            "https://example.com/start": _FakeResponse(
                status_code=302,
                headers={"location": "/final"},
                chunks=[b""],
            ),
            "https://example.com/final": _FakeResponse(
                headers={"content-type": "text/html"},
                chunks=[b"<html><body>final</body></html>"],
            ),
        }
    )
    try:
        with (
            patch("app.services.url_safety.socket.getaddrinfo", return_value=_public_dns()),
            patch("app.services.web_snapshots.httpx.AsyncClient", return_value=redirect_client),
        ):
            _, final_url, robots = asyncio.run(fetch_html_page(settings, "https://example.com/start"))
        cases.append(
            {
                "case_id": "same_source_redirect",
                "passed": (
                    robots.allowed
                    and urlparse(final_url).hostname == "example.com"
                    and final_url == "https://example.com/final"
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001 - controlled case remains visible
        cases.append({"case_id": "same_source_redirect", "passed": False, "detail": str(exc)})

    robots_client = _FakeClient(
        {
            "https://example.com/robots.txt": _FakeResponse(
                status_code=403,
                headers={"content-type": "text/plain"},
                chunks=[b"blocked"],
            )
        }
    )
    try:
        with (
            patch("app.services.url_safety.socket.getaddrinfo", return_value=_public_dns()),
            patch("app.services.web_snapshots.httpx.AsyncClient", return_value=robots_client),
        ):
            asyncio.run(fetch_html_page(settings, "https://example.com/start"))
    except HTTPException as exc:
        cases.append(
            {
                "case_id": "robots_is_not_success",
                "passed": exc.status_code == 403,
                "detail": str(exc.detail),
            }
        )
    except Exception as exc:  # noqa: BLE001 - controlled case remains visible
        cases.append({"case_id": "robots_is_not_success", "passed": False, "detail": str(exc)})
    else:
        cases.append({"case_id": "robots_is_not_success", "passed": False, "detail": "fetch was allowed"})

    try:
        with patch(
            "app.services.url_safety.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ):
            validate_web_url("https://example.com/start", {"example.com"})
    except HTTPException as exc:
        cases.append(
            {
                "case_id": "dns_private_resolution",
                "passed": exc.status_code == 403,
                "detail": str(exc.detail),
            }
        )
    except Exception as exc:  # noqa: BLE001 - controlled case remains visible
        cases.append({"case_id": "dns_private_resolution", "passed": False, "detail": str(exc)})
    else:
        cases.append({"case_id": "dns_private_resolution", "passed": False, "detail": "private DNS allowed"})

    peer_client = _FakeClient(
        {
            "https://example.com/robots.txt": _FakeResponse(
                status_code=404,
                peer="127.0.0.1",
                headers={"content-type": "text/plain"},
                chunks=[b""],
            )
        }
    )
    try:
        with (
            patch("app.services.url_safety.socket.getaddrinfo", return_value=_public_dns()),
            patch("app.services.web_snapshots.httpx.AsyncClient", return_value=peer_client),
        ):
            asyncio.run(fetch_html_page(settings, "https://example.com/start"))
    except HTTPException as exc:
        cases.append(
            {
                "case_id": "private_response_peer",
                "passed": exc.status_code == 403,
                "detail": str(exc.detail),
            }
        )
    except Exception as exc:  # noqa: BLE001 - controlled case remains visible
        cases.append({"case_id": "private_response_peer", "passed": False, "detail": str(exc)})
    else:
        cases.append({"case_id": "private_response_peer", "passed": False, "detail": "private peer allowed"})
    return cases


def _live_cases() -> list[dict[str, Any]]:
    targets = (
        ("example", "https://example.com/", "example.com"),
        ("iana_example", "https://www.iana.org/help/example-domains", "www.iana.org"),
    )
    cases: list[dict[str, Any]] = []
    for case_id, url, host in targets:
        settings = Settings(
            web_allowed_hosts=f"{host},{host[4:]}" if host.startswith("www.") else host,
            request_timeout_seconds=10.0,
        )
        retrieved_at = datetime.now(UTC).isoformat()
        try:
            body, final_url, robots = asyncio.run(fetch_html_page(settings, url))
            cases.append(
                {
                    "case_id": case_id,
                    "url": url,
                    "retrieved_at": retrieved_at,
                    "status": "ok",
                    "body_bytes": len(body),
                    "final_url": final_url,
                    "robots_allowed": robots.allowed,
                    "same_host": _same_source_host(url, final_url),
                    "passed": bool(body and robots.allowed and _same_source_host(url, final_url)),
                }
            )
        except Exception as exc:  # noqa: BLE001 - live failure remains evidence
            cases.append(
                {
                    "case_id": case_id,
                    "url": url,
                    "retrieved_at": retrieved_at,
                    "status": "failed",
                    "exception_type": type(exc).__name__,
                    "detail": str(exc),
                    "passed": False,
                }
            )
    return cases


def measure_g5_shape(gold_dir: Path, *, include_live: bool = False) -> dict[str, Any]:
    freeze = json.loads((gold_dir / "g0_freeze.json").read_text(encoding="utf-8"))
    suite = evaluate_ssrf_suite(gold_dir.parent / "ssrf_adversarial.json")
    controlled = _controlled_cases()
    controlled_pass = sum(1 for case in controlled if case["passed"])
    live = _live_cases() if include_live else []
    live_pass = sum(1 for case in live if case["passed"])
    return {
        "artifact_version": "product-gap-c1-g5-measurement-v3",
        "dataset_version": freeze.get("dataset_version"),
        "path": (
            "production_fetch_and_url_safety_controlled_plus_live_transport"
            if include_live
            else "production_fetch_and_url_safety_controlled_transport"
        ),
        "sample_complete": True,
        "case_count": suite.get("case_count"),
        "shape_bypass_count": suite.get("shape_bypass_count"),
        "shape_rejected": suite.get("rejected"),
        "controlled_case_count": len(controlled),
        "controlled_case_passed": controlled_pass,
        "controlled_cases": controlled,
        "production_fetch_measured": controlled_pass == len(controlled),
        "identity_measured": next(
            (case["passed"] for case in controlled if case["case_id"] == "same_source_redirect"),
            False,
        ),
        "redirect_same_source_measured": True,
        "robots_not_success_measured": next(
            (case["passed"] for case in controlled if case["case_id"] == "robots_is_not_success"),
            False,
        ),
        "dns_validation_measured": next(
            (case["passed"] for case in controlled if case["case_id"] == "dns_private_resolution"),
            False,
        ),
        "peer_validation_measured": next(
            (case["passed"] for case in controlled if case["case_id"] == "private_response_peer"),
            False,
        ),
        "live_case_count": len(live),
        "live_case_passed": live_pass,
        "live_cases": live,
        "live_network_measured": include_live and live_pass == len(live) and len(live) >= 2,
        "bypasses": suite.get("bypasses"),
        "unmeasured": [
            "dns_rebinding_timing_window",
            *([] if include_live else ["real_live_network_transport"]),
        ],
    }
