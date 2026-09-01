"""Deterministic SSRF shape/host checks for the Challenge-1 G5 suite."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException

from app.services.url_safety import validate_url_shape

PRIVATE_HOST_MARKERS = (
    "localhost",
    "localdomain",
    "metadata.google.internal",
    "host.docker.internal",
    "kubernetes.default.svc",
    ".internal",
    ".corp",
    ".home",
    ".lan",
    ".local",
    ".onion",
    ".i2p",
    ".consul",
    "nip.io",
    "sslip.io",
    "xip.io",
    "localtest.me",
    "lvh.me",
    "vcap.me",
)


@dataclass(frozen=True)
class SsrfCaseResult:
    case_id: str
    url: str
    rejected: bool
    reason: str


def _host_is_blocked(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    if any(marker in host for marker in (" ", "\t", "\x00", "%00", "%2f")):
        return True
    if any(marker in host for marker in PRIVATE_HOST_MARKERS):
        return True
    if "127.0.0.1" in host or host.startswith("127."):
        return True
    stripped = host.strip("[]")
    if stripped.startswith("0x") or stripped.startswith("::") or stripped.startswith("ff"):
        return True
    if stripped.isdigit() and int(stripped) <= 0xFFFFFFFF:
        return True
    parts = stripped.split(".")
    if 1 <= len(parts) <= 4 and all(part for part in parts):
        if any(part.startswith("0x") or (part.startswith("0") and part != "0" and part.isdigit()) for part in parts):
            return True
        if len(parts) < 4 and all(part.isdigit() for part in parts):
            return True
    try:
        ip = ipaddress.ip_address(stripped)
    except ValueError:
        return False
    return bool(
        ip.is_multicast
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def classify_url(url: str) -> SsrfCaseResult:
    lowered = url.lower()
    if any(token in lowered for token in ("%00", "%2f", "\t", " ")):
        return SsrfCaseResult("pending", url, True, "encoded_or_whitespace")
    try:
        parsed = validate_url_shape(url, source_name="SSRF")
    except HTTPException as exc:
        return SsrfCaseResult("pending", url, True, str(exc.detail))
    host = parsed.hostname or ""
    if _host_is_blocked(host):
        return SsrfCaseResult("pending", url, True, "blocked_host")
    return SsrfCaseResult("pending", url, False, "shape_ok")


def evaluate_ssrf_suite(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results: list[SsrfCaseResult] = []
    bypasses: list[str] = []
    for item in payload["cases"]:
        classified = classify_url(item["url"])
        row = SsrfCaseResult(item["id"], item["url"], classified.rejected, classified.reason)
        results.append(row)
        if item["expect"] == "reject" and not row.rejected:
            bypasses.append(item["id"])
    return {
        "suite_version": payload["suite_version"],
        "case_count": len(results),
        "rejected": sum(1 for row in results if row.rejected),
        "bypasses": bypasses,
        "pass": len(results) >= 100 and not bypasses,
    }
