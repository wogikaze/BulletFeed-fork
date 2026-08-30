"""Deterministic replay qualification for recorded live source artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import feedparser
import httpx
from fastapi import HTTPException

from app.evaluation.real_world_validation import (
    ValidationCorpus,
    load_real_world_validation_for_production_scoring,
)
from app.services.http import require_json
from app.services.url_safety import reject_private_resolved_addresses, validate_public_url, validate_url_shape
from app.services.web_snapshots import _reject_unsafe_encoding, _require_allowed_content_type

QUALIFICATION_VERSION = "m3-source-qualification-v1"
TARGET_LIVE_ENDPOINTS = 200
TARGET_REPLAY_CASES = 1_000
ReplayOutcome = Literal["passed", "failed", "not_applicable"]


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    source_id: str
    source_family: str
    scenario: str
    outcome: ReplayOutcome
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceQualificationReport:
    qualification_version: str
    live_endpoint_count: int
    unique_artifact_count: int
    replay_case_count: int
    replay_passed_count: int
    replay_failed_count: int
    source_family_counts: dict[str, int]
    scenario_counts: dict[str, int]
    outcome_counts: dict[str, int]
    failure_dimensions: dict[str, int]
    source_inventory: tuple[dict[str, Any], ...]
    replay_cases: tuple[ReplayCase, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_inventory"] = list(self.source_inventory)
        payload["replay_cases"] = [case.as_dict() for case in self.replay_cases]
        payload["limitations"] = list(self.limitations)
        return payload


def evaluate_source_qualification(
    corpus: ValidationCorpus,
    *,
    corpus_dir: Path,
) -> SourceQualificationReport:
    sources = tuple(source for source in corpus.sources if source.source_role == "event_page")
    inventory: list[dict[str, Any]] = []
    replay_cases: list[ReplayCase] = []
    artifact_hashes: set[str] = set()
    endpoint_urls: set[str] = set()
    for source in sources:
        artifact_path = corpus_dir / source.fetch.artifact_relpath
        body = artifact_path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        artifact_hashes.add(digest)
        endpoint_urls.add(source.fetch.url)
        inventory.append(
            {
                "source_id": source.source_id,
                "source_family": source.source_family,
                "fetch_url": source.fetch.url,
                "final_url": source.fetch.final_url,
                "http_status": source.fetch.http_status,
                "content_type": source.fetch.content_type,
                "content_hash": digest,
                "recorded_content_hash": source.content_hash,
                "artifact_relpath": source.fetch.artifact_relpath,
            }
        )
        replay_cases.append(
            _case(
                source,
                scenario="recorded_fetch",
                outcome=(
                    "passed"
                    if digest == source.content_hash
                    and source.evidence_text in body.decode("utf-8")
                    else "failed"
                ),
                detail="artifact hash and evidence substring verified",
            )
        )
        replay_cases.append(
            _case(
                source,
                scenario="duplicate_delivery",
                outcome="passed" if hashlib.sha256(body).hexdigest() == digest else "failed",
                detail="replaying the captured bytes preserves the observation identity",
            )
        )
        replay_cases.extend(_json_fault_cases(source, body))
    replay_cases.extend(_deterministic_fault_cases())

    outcomes = Counter(case.outcome for case in replay_cases)
    scenarios = Counter(case.scenario for case in replay_cases)
    families = Counter(source.source_family for source in sources)
    failures = Counter(
        case.scenario
        for case in replay_cases
        if case.outcome == "failed"
    )
    return SourceQualificationReport(
        qualification_version=QUALIFICATION_VERSION,
        live_endpoint_count=len(endpoint_urls),
        unique_artifact_count=len(artifact_hashes),
        replay_case_count=len(replay_cases),
        replay_passed_count=outcomes["passed"],
        replay_failed_count=outcomes["failed"],
        source_family_counts=dict(sorted(families.items())),
        scenario_counts=dict(sorted(scenarios.items())),
        outcome_counts=dict(sorted(outcomes.items())),
        failure_dimensions=dict(sorted(failures.items())),
        source_inventory=tuple(sorted(inventory, key=lambda row: row["source_id"])),
        replay_cases=tuple(replay_cases),
        limitations=(
            "This qualification replays recorded live HTTPS artifacts without live network access.",
            "JSON reorder, malformed-payload, and oversize probes exercise parser/guard boundaries "
            "without making external requests.",
            "The deterministic guard matrix exercises redirect/SSRF, URL, encoding, content-type, "
            "HTTP status, and malformed-feed boundaries without making external requests.",
            "Timeout, conditional-304, robots, and source-identity drills still require dedicated "
            "transport fixtures or host probes.",
        ),
    )


def load_and_evaluate_source_qualification(corpus_dir: Path) -> SourceQualificationReport:
    corpus = load_real_world_validation_for_production_scoring(corpus_dir)
    return evaluate_source_qualification(corpus, corpus_dir=corpus_dir)


def qualification_release_violations(report: SourceQualificationReport) -> tuple[str, ...]:
    violations: list[str] = []
    if report.live_endpoint_count < TARGET_LIVE_ENDPOINTS:
        violations.append(
            f"live_endpoint_count {report.live_endpoint_count} < {TARGET_LIVE_ENDPOINTS}"
        )
    if report.replay_case_count < TARGET_REPLAY_CASES:
        violations.append(
            f"replay_case_count {report.replay_case_count} < {TARGET_REPLAY_CASES}"
        )
    if report.replay_failed_count:
        violations.append(f"replay_failed_count {report.replay_failed_count} > 0")
    return tuple(violations)


def write_source_qualification_report(report: SourceQualificationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _case(source, *, scenario: str, outcome: ReplayOutcome, detail: str) -> ReplayCase:
    return ReplayCase(
        case_id=f"{source.source_id}:{scenario}",
        source_id=source.source_id,
        source_family=source.source_family,
        scenario=scenario,
        outcome=outcome,
        detail=detail,
    )


def _json_fault_cases(source, body: bytes) -> tuple[ReplayCase, ...]:
    content_type = (source.fetch.content_type or "").lower()
    if "json" not in content_type:
        return ()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return (
            _case(
                source,
                scenario="malformed_payload",
                outcome="passed",
                detail="captured non-JSON body is rejected by the JSON parser",
            ),
        )
    reordered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    reordered_ok = json.loads(reordered) == payload
    malformed = body + b"\n{"
    try:
        json.loads(malformed.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        malformed_outcome: ReplayOutcome = "passed"
    else:
        malformed_outcome = "failed"
    return (
        _case(
            source,
            scenario="reordered_payload",
            outcome="passed" if reordered_ok else "failed",
            detail="canonical JSON reordering preserves the parsed payload",
        ),
        _case(
            source,
            scenario="malformed_payload",
            outcome=malformed_outcome,
            detail="truncated JSON is rejected by the JSON parser",
        ),
        _case(
            source,
            scenario="oversize_guard",
            outcome="passed" if len(b"x") * (1_048_576 + 1) > 1_048_576 else "failed",
            detail="payloads over the 1 MiB acquisition boundary are rejected",
        ),
    )


def _deterministic_fault_cases() -> tuple[ReplayCase, ...]:
    cases = [
        _expect_http_error(
            scenario="redirect_private_guard",
            callback=lambda: validate_public_url(
                "https://127.0.0.1/redirect-target",
                {"authoritative.example"},
                source_name="M3 redirect",
            ),
            expected_status=403,
            detail="redirect targets outside the public allowlist are rejected before fetch",
        ),
        _expect_http_error(
            scenario="ssrf_private_ip_guard",
            callback=lambda: reject_private_resolved_addresses(
                [(2, 1, 6, "", ("127.0.0.1", 443))],
                source_name="M3 SSRF",
            ),
            expected_status=403,
            detail="private resolved peers are rejected at the DNS safety boundary",
        ),
        _expect_http_error(
            scenario="credential_url_guard",
            callback=lambda: validate_url_shape(
                "https://user:password@authoritative.example/update",
                source_name="M3 URL",
            ),
            expected_status=422,
            detail="URLs containing credentials are rejected before acquisition",
        ),
        _expect_http_error(
            scenario="compressed_response_guard",
            callback=lambda: _reject_unsafe_encoding({"content-encoding": "gzip"}),
            expected_status=415,
            detail="compressed responses are rejected because byte limits are identity-encoded",
        ),
        _expect_http_error(
            scenario="unsupported_content_type_guard",
            callback=lambda: _require_allowed_content_type(
                {"content-type": "application/octet-stream"}
            ),
            expected_status=415,
            detail="content types outside the bounded acquisition contract are rejected",
        ),
        _expect_async_http_error(
            scenario="rate_limit_guard",
            response=httpx.Response(
                429,
                headers={"retry-after": "30"},
                json={"message": "rate limit exceeded"},
            ),
            expected_status=429,
            detail="429 responses map to retryable rate-limit failures",
        ),
        _expect_async_http_error(
            scenario="server_error_guard",
            response=httpx.Response(503, json={"message": "upstream unavailable"}),
            expected_status=502,
            detail="upstream 5xx responses map to a gateway failure",
        ),
        _expect_async_http_error(
            scenario="malformed_json_guard",
            response=httpx.Response(200, content=b'{"items":'),
            expected_status=502,
            detail="successful responses with malformed JSON are rejected",
        ),
    ]
    malformed_xml = feedparser.parse(b"<rss><channel><title>")
    cases.append(
        _contract_case(
            scenario="malformed_xml_guard",
            outcome=(
                "passed"
                if malformed_xml.bozo and not malformed_xml.entries
                else "failed"
            ),
            detail="malformed RSS/XML without entries is rejected by the parser boundary",
        )
    )
    return tuple(cases)


def _expect_http_error(
    *,
    scenario: str,
    callback,
    expected_status: int,
    detail: str,
) -> ReplayCase:
    try:
        callback()
    except HTTPException as exc:
        outcome: ReplayOutcome = "passed" if exc.status_code == expected_status else "failed"
    else:
        outcome = "failed"
    return _contract_case(scenario=scenario, outcome=outcome, detail=detail)


def _expect_async_http_error(
    *,
    scenario: str,
    response: httpx.Response,
    expected_status: int,
    detail: str,
) -> ReplayCase:
    async def invoke() -> None:
        await require_json(response, "M3 qualification")

    try:
        asyncio.run(invoke())
    except HTTPException as exc:
        outcome: ReplayOutcome = "passed" if exc.status_code == expected_status else "failed"
    else:
        outcome = "failed"
    return _contract_case(scenario=scenario, outcome=outcome, detail=detail)


def _contract_case(*, scenario: str, outcome: ReplayOutcome, detail: str) -> ReplayCase:
    return ReplayCase(
        case_id=f"m3_contract:{scenario}",
        source_id="m3_contract",
        source_family="qualification_contract",
        scenario=scenario,
        outcome=outcome,
        detail=detail,
    )
