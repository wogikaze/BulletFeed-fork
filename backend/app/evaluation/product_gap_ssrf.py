"""G5 SSRF suite scored only through production URL shape checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.services.url_safety import validate_url_shape


@dataclass(frozen=True)
class SsrfCaseResult:
    case_id: str
    url: str
    rejected: bool
    reason: str


def classify_url(url: str) -> SsrfCaseResult:
    try:
        validate_url_shape(url, source_name="SSRF")
    except HTTPException as exc:
        return SsrfCaseResult("pending", url, True, str(exc.detail))
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
        "production_path": "validate_url_shape",
        "production_fetch_measured": False,
        "passed": False,
        "failures": (["g5_production_fetch_unmeasured"] + (["g5_ssrf_shape_bypass"] if bypasses else [])),
        "shape_bypass_count": len(bypasses),
    }
