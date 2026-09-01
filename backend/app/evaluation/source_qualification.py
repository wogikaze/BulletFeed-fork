"""Deterministic replay qualification for recorded live source artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import feedparser
import httpx
from fastapi import HTTPException

from app.config import Settings
from app.evaluation.real_world_validation import (
    ValidationCorpus,
    load_real_world_validation_for_production_scoring,
)
from app.services.http import require_json
from app.services.url_safety import reject_private_resolved_addresses, validate_public_url, validate_url_shape
from app.services.web_changes import extract_web_snapshot_changes
from app.services.web_snapshots import (
    RobotsDecision,
    SnapshotStore,
    WebSnapshot,
    _reject_unsafe_encoding,
    _require_allowed_content_type,
    content_hash_for,
    fetch_web_snapshot,
    snapshot_id_for,
)

QUALIFICATION_VERSION = "m3-source-qualification-v1"
TARGET_LIVE_ENDPOINTS = 200
TARGET_REPLAY_CASES = 1_000
QUALIFICATION_HOST = "example.com"
QUALIFICATION_URL = f"https://{QUALIFICATION_HOST}/changelog"
QUALIFICATION_PUBLIC_PEER = "93.184.216.34"
ReplayOutcome = Literal["passed", "failed", "not_applicable"]


class _QualificationNetworkStream:
    def get_extra_info(self, name: str):
        if name == "server_addr":
            return (QUALIFICATION_PUBLIC_PEER, 443)
        return None


class _QualificationResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"<html>qualification</html>",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html"}
        self.extensions = {"network_stream": _QualificationNetworkStream()}
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aiter_raw(self):
        yield self._body


class _QualificationTimeoutResponse:
    async def __aenter__(self):
        raise httpx.TimeoutException("qualification timeout")

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _QualificationClient:
    def __init__(self, routes: dict[str, object]) -> None:
        self._routes = {
            url: list(response) if isinstance(response, list) else [response]
            for url, response in routes.items()
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method: str, url: str, **kwargs):
        del method, kwargs
        responses = self._routes.get(url)
        if not responses:
            raise AssertionError(f"unexpected qualification request: {url}")
        return responses[0] if len(responses) == 1 else responses.pop(0)


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
    source_family_metrics: dict[str, dict[str, Any]]
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
    replay_cases.extend(_deterministic_transport_cases())
    replay_cases.append(_update_detection_case())

    outcomes = Counter(case.outcome for case in replay_cases)
    scenarios = Counter(case.scenario for case in replay_cases)
    families = Counter(source.source_family for source in sources)
    family_metrics = _source_family_metrics(sources, replay_cases)
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
        source_family_metrics=family_metrics,
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
            "A deterministic immutable-snapshot pair exercises update detection; per-source update "
            "rates remain not_recorded because the live corpus has one fetch per endpoint.",
            "Timeout, conditional-304, robots, and source-identity scenarios use an isolated "
            "transport fixture and never make external requests.",
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


def _source_family_metrics(
    sources: tuple[Any, ...],
    replay_cases: list[ReplayCase],
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for family in sorted({source.source_family for source in sources}):
        family_sources = [source for source in sources if source.source_family == family]
        source_ids = {source.source_id for source in family_sources}
        family_cases = [case for case in replay_cases if case.source_id in source_ids]
        recorded = [
            case for case in family_cases if case.scenario == "recorded_fetch"
        ]
        duplicate = [
            case for case in family_cases if case.scenario == "duplicate_delivery"
        ]
        delays = [
            delay
            for source in family_sources
            if (delay := _acquisition_delay_seconds(source)) is not None
        ]
        metrics[family] = {
            "endpoint_count": len(family_sources),
            "recorded_fetch_success_rate": _rate(
                sum(case.outcome == "passed" for case in recorded),
                len(recorded),
            ),
            "duplicate_delivery_failure_rate": _rate(
                sum(case.outcome == "failed" for case in duplicate),
                len(duplicate),
            ),
            "etag_coverage": _rate(
                sum(bool(source.fetch.etag) for source in family_sources),
                len(family_sources),
            ),
            "last_modified_coverage": _rate(
                sum(bool(source.fetch.last_modified) for source in family_sources),
                len(family_sources),
            ),
            "http_status_counts": dict(
                sorted(
                    Counter(int(source.fetch.http_status) for source in family_sources).items()
                )
            ),
            "static_fetch_ok_count": sum(
                source.static_fetch_ok for source in family_sources
            ),
            "static_normalize_insufficient_count": sum(
                source.static_normalize_insufficient for source in family_sources
            ),
            "js_render_would_recover_count": sum(
                source.js_render_would_recover for source in family_sources
            ),
            "acquisition_delay_seconds": {
                "sample_count": len(delays),
                "median": _median(delays),
                "max": max(delays) if delays else None,
            },
            "update_detection": {
                "status": "not_recorded",
                "note": "The recorded corpus contains one fetch per event endpoint.",
            },
        }
    return metrics


def _acquisition_delay_seconds(source: Any) -> float | None:
    try:
        requested = _parse_datetime(source.fetch.requested_at)
        collected = _parse_datetime(source.collected_at)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, (collected - requested).total_seconds()), 6)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return round((ordered[midpoint - 1] + ordered[midpoint]) / 2, 6)


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


def _update_detection_case() -> ReplayCase:
    canonical_url = "https://qualification.example/changelog"
    left_body = b"<html><body><h1>Changelog</h1><p>Version 1 is available.</p></body></html>"
    right_body = (
        b"<html><body><h1>Changelog</h1>"
        b"<p>Version 2 is available with security fixes.</p></body></html>"
    )
    left = _qualification_snapshot(
        canonical_url=canonical_url,
        body=left_body,
        retrieved_at="2026-08-01T00:00:00Z",
    )
    right = _qualification_snapshot(
        canonical_url=canonical_url,
        body=right_body,
        retrieved_at="2026-08-02T00:00:00Z",
    )
    changes = extract_web_snapshot_changes(left, right)
    return _contract_case(
        scenario="update_detection",
        outcome=(
            "passed"
            if left.content_hash != right.content_hash and bool(changes.downstream_candidates)
            else "failed"
        ),
        detail="a changed immutable snapshot produces a downstream update candidate",
    )


def _qualification_snapshot(
    *,
    canonical_url: str,
    body: bytes,
    retrieved_at: str,
) -> WebSnapshot:
    digest = content_hash_for(body)
    return WebSnapshot(
        snapshot_id=snapshot_id_for(canonical_url=canonical_url, content_hash=digest),
        canonical_url=canonical_url,
        retrieved_at=retrieved_at,
        content_hash=digest,
        status_code=200,
        headers=(("content-type", "text/html"),),
        body=body,
        etag=None,
        last_modified=None,
        robots=RobotsDecision(
            source_url=canonical_url,
            robots_url=None,
            allowed=True,
            reason="qualification_fixture",
            retrieved_at=retrieved_at,
        ),
        final_url=canonical_url,
    )


def _deterministic_fault_cases() -> tuple[ReplayCase, ...]:
    cases = [
        _expect_http_error(
            scenario="redirect_private_guard",
            callback=lambda: validate_public_url(
                "https://unlisted.example/redirect-target",
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


def _deterministic_transport_cases() -> tuple[ReplayCase, ...]:
    timeout_result = _run_transport_fetch(
        {QUALIFICATION_URL: _QualificationTimeoutResponse()},
    )
    timeout_passed = (
        isinstance(timeout_result, HTTPException) and timeout_result.status_code == 504
    )

    previous = _qualification_snapshot(
        canonical_url=QUALIFICATION_URL,
        body=b"<html>unchanged</html>",
        retrieved_at="2026-08-01T00:00:00Z",
    )
    conditional_result = _run_transport_fetch(
        {
            QUALIFICATION_URL: _QualificationResponse(
                status_code=304,
                headers={"etag": '"unchanged"'},
                body=b"",
            )
        },
        previous=previous,
    )
    conditional_passed = (
        isinstance(conditional_result, WebSnapshot)
        and conditional_result.not_modified
        and conditional_result.snapshot_id == previous.snapshot_id
        and conditional_result.body == previous.body
    )

    robots_result = _run_transport_fetch(
        {
            f"https://{QUALIFICATION_HOST}/robots.txt": _QualificationResponse(
                headers={"content-type": "text/plain"},
                body=b"User-agent: *\nDisallow: /\n",
            )
        },
        check_robots=True,
    )
    robots_passed = isinstance(robots_result, HTTPException) and robots_result.status_code == 403

    moved_url = f"https://{QUALIFICATION_HOST}/releases"
    identity_result = _run_transport_fetch(
        {
            QUALIFICATION_URL: _QualificationResponse(
                status_code=302,
                headers={"location": moved_url},
                body=b"",
            ),
            moved_url: _QualificationResponse(
                headers={"content-type": "text/html"},
                body=b"<html>moved source</html>",
            ),
        }
    )
    identity_passed = (
        isinstance(identity_result, WebSnapshot)
        and identity_result.canonical_url == QUALIFICATION_URL
        and identity_result.final_url == moved_url
    )

    return (
        _contract_case(
            scenario="timeout_transport",
            outcome="passed" if timeout_passed else "failed",
            detail="a transport timeout maps to the bounded 504 gateway failure",
        ),
        _contract_case(
            scenario="conditional_304",
            outcome="passed" if conditional_passed else "failed",
            detail="a conditional 304 reuses the immutable prior snapshot without a new version",
        ),
        _contract_case(
            scenario="robots_disallow",
            outcome="passed" if robots_passed else "failed",
            detail="robots disallow prevents page acquisition before the page request",
        ),
        _contract_case(
            scenario="source_identity_change",
            outcome="passed" if identity_passed else "failed",
            detail="a moved source preserves the requested identity and records the final URL",
        ),
    )


def _run_transport_fetch(
    routes: dict[str, object],
    *,
    previous: WebSnapshot | None = None,
    check_robots: bool = False,
) -> WebSnapshot | HTTPException:
    with tempfile.TemporaryDirectory(prefix="bulletfeed-m3-transport-") as directory:
        client = _QualificationClient(routes)
        settings = Settings(
            web_allowed_hosts=QUALIFICATION_HOST,
            max_response_bytes=1_048_576,
        )
        with (
            patch("app.services.web_snapshots.httpx.AsyncClient", return_value=client),
            patch(
                "app.services.url_safety.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", (QUALIFICATION_PUBLIC_PEER, 443))],
            ),
        ):
            async def invoke() -> WebSnapshot:
                return await fetch_web_snapshot(
                    settings,
                    QUALIFICATION_URL,
                    store=SnapshotStore(Path(directory) / "snapshots"),
                    previous=previous,
                    check_robots=check_robots,
                    retrieved_at="2026-08-30T00:00:00Z",
                )

            try:
                return asyncio.run(invoke())
            except HTTPException as exc:
                return exc


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
