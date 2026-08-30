"""Qualify a deterministic sample of recorded source endpoints over live HTTPS."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any

import httpx
from fastapi import HTTPException

from app.evaluation.real_world_validation import load_real_world_validation_for_production_scoring
from app.services.url_safety import (
    require_global_response_peer,
    resolve_public_hostname,
    validate_url_shape,
)

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "gold" / "real_world_validation" / "v01"
QUALIFICATION_VERSION = "m3-live-source-qualification-v1"
TARGET_ENDPOINTS = 200
MAX_RESPONSE_BYTES = 1_048_576
REQUEST_TIMEOUT_SECONDS = 12.0


@dataclass(frozen=True)
class EndpointResult:
    fetch_url: str
    source_id: str
    source_family: str
    status_code: int | None
    outcome: str
    latency_ms: float
    content_length: int
    content_type: str | None
    final_url: str | None
    live_content_hash: str | None
    recorded_hash_match: bool | None
    error_type: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveQualificationReport:
    qualification_version: str
    endpoint_count: int
    source_family_counts: dict[str, int]
    outcome_counts: dict[str, int]
    failure_dimensions: dict[str, int]
    median_latency_ms: float
    success_rate: float
    by_source_family: dict[str, dict[str, Any]]
    endpoints: tuple[EndpointResult, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["endpoints"] = [item.as_dict() for item in self.endpoints]
        payload["limitations"] = list(self.limitations)
        return payload


def _select_endpoints(corpus, limit: int) -> tuple[Any, ...]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    seen: set[str] = set()
    for source in corpus.sources:
        if source.source_role != "event_page" or source.fetch.url in seen:
            continue
        seen.add(source.fetch.url)
        grouped[source.source_family].append(source)
    selected: list[Any] = []
    families = sorted(grouped)
    while len(selected) < limit and any(grouped.values()):
        for family in families:
            if grouped[family] and len(selected) < limit:
                selected.append(grouped[family].pop(0))
    return tuple(selected)


async def _fetch_endpoint(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    source: Any,
) -> EndpointResult:
    started = time.perf_counter()
    url = source.fetch.url
    try:
        parsed = validate_url_shape(url, source_name="M3 live qualification")
        if parsed.hostname is None:
            raise HTTPException(status_code=422, detail="source host is missing")
        resolve_public_hostname(parsed.hostname, port=443, source_name="M3 live qualification")
        async with semaphore:
            async with client.stream("GET", url) as response:
                require_global_response_peer(response, source_name="M3 live qualification")
                status = response.status_code
                content_type = response.headers.get("content-type")
                final_url = str(response.url)
                elapsed = (time.perf_counter() - started) * 1_000
                if 300 <= status < 400:
                    return _result(
                        source,
                        status_code=status,
                        outcome="redirect",
                        latency_ms=elapsed,
                        content_length=0,
                        content_type=content_type,
                        final_url=final_url,
                    )
                if status == 429:
                    return _result(
                        source,
                        status_code=status,
                        outcome="rate_limit",
                        latency_ms=elapsed,
                        content_length=0,
                        content_type=content_type,
                        final_url=final_url,
                    )
                if status != 200:
                    return _result(
                        source,
                        status_code=status,
                        outcome="http_error",
                        latency_ms=elapsed,
                        content_length=0,
                        content_type=content_type,
                        final_url=final_url,
                    )
                body = bytearray()
                async for chunk in response.aiter_raw():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        return _result(
                            source,
                            status_code=status,
                            outcome="oversize",
                            latency_ms=(time.perf_counter() - started) * 1_000,
                            content_length=len(body),
                            content_type=content_type,
                            final_url=final_url,
                        )
                digest = hashlib.sha256(body).hexdigest()
                return _result(
                    source,
                    status_code=status,
                    outcome="success",
                    latency_ms=(time.perf_counter() - started) * 1_000,
                    content_length=len(body),
                    content_type=content_type,
                    final_url=final_url,
                    live_content_hash=digest,
                    recorded_hash_match=digest == source.content_hash,
                )
    except HTTPException as exc:
        return _result(
            source,
            status_code=exc.status_code,
            outcome="url_safety",
            latency_ms=(time.perf_counter() - started) * 1_000,
            content_length=0,
            error_type=str(exc.detail),
        )
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        return _result(
            source,
            status_code=None,
            outcome="network_error",
            latency_ms=(time.perf_counter() - started) * 1_000,
            content_length=0,
            error_type=type(exc).__name__,
        )


def _result(
    source: Any,
    *,
    status_code: int | None,
    outcome: str,
    latency_ms: float,
    content_length: int,
    content_type: str | None = None,
    final_url: str | None = None,
    live_content_hash: str | None = None,
    recorded_hash_match: bool | None = None,
    error_type: str | None = None,
) -> EndpointResult:
    return EndpointResult(
        fetch_url=source.fetch.url,
        source_id=source.source_id,
        source_family=source.source_family,
        status_code=status_code,
        outcome=outcome,
        latency_ms=round(latency_ms, 3),
        content_length=content_length,
        content_type=content_type,
        final_url=final_url,
        live_content_hash=live_content_hash,
        recorded_hash_match=recorded_hash_match,
        error_type=error_type,
    )


async def _evaluate(corpus, *, limit: int, concurrency: int) -> LiveQualificationReport:
    selected = _select_endpoints(corpus, limit)
    semaphore = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "BulletFeed/qualification-live"},
    ) as client:
        results = await asyncio.gather(
            *(_fetch_endpoint(client, semaphore, source) for source in selected)
        )
    outcome_counts = Counter(result.outcome for result in results)
    family_counts = Counter(result.source_family for result in results)
    failures = Counter(result.outcome for result in results if result.outcome != "success")
    latencies = [result.latency_ms for result in results]
    by_family: dict[str, dict[str, Any]] = {}
    for family in sorted(family_counts):
        scoped = [result for result in results if result.source_family == family]
        by_family[family] = {
            "endpoint_count": len(scoped),
            "success_count": sum(result.outcome == "success" for result in scoped),
            "outcomes": dict(sorted(Counter(result.outcome for result in scoped).items())),
            "median_latency_ms": round(median(result.latency_ms for result in scoped), 3),
        }
    return LiveQualificationReport(
        qualification_version=QUALIFICATION_VERSION,
        endpoint_count=len(results),
        source_family_counts=dict(sorted(family_counts.items())),
        outcome_counts=dict(sorted(outcome_counts.items())),
        failure_dimensions=dict(sorted(failures.items())),
        median_latency_ms=round(median(latencies) if latencies else 0.0, 3),
        success_rate=(sum(result.outcome == "success" for result in results) / len(results))
        if results
        else 0.0,
        by_source_family=by_family,
        endpoints=tuple(sorted(results, key=lambda result: result.fetch_url)),
        limitations=(
            "Live qualification uses a deterministic sample and does not follow redirects.",
            "No live response body is persisted; recorded artifact provenance remains the replay source.",
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.limit < 1 or args.concurrency < 1:
        raise ValueError("live qualification limits must be positive")
    corpus = load_real_world_validation_for_production_scoring(CORPUS)
    report = asyncio.run(_evaluate(corpus, limit=args.limit, concurrency=args.concurrency))
    payload = json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    if args.check and report.endpoint_count < TARGET_ENDPOINTS:
        print(
            f"live endpoint floor failed: {report.endpoint_count} < {TARGET_ENDPOINTS}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
