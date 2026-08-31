"""Collect or replay #283 t1 observations. Live fetch is opt-in and not PR CI."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from app.evaluation.longitudinal_qualification import (
    PROTOCOL_VERSION,
    Observation,
    classify_pair,
    summarize_outcomes,
)
from app.services.url_safety import (
    require_global_response_peer,
    resolve_public_hostname,
    validate_url_shape,
)

BACKEND = Path(__file__).resolve().parents[1]
PROTOCOL = BACKEND / "tests" / "gold" / "source_qualification" / "v01" / "longitudinal_protocol.json"
MAX_RESPONSE_BYTES = 1_048_576
REQUEST_TIMEOUT_SECONDS = 12.0


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _t0_observation(row: dict[str, Any]) -> Observation:
    return Observation(
        source_id=str(row["source_id"]),
        source_family=str(row["source_family"]),
        fetch_url=str(row["fetch_url"]),
        acquired_at=str(row.get("t0_acquired_at") or "t0_recorded_live_sample"),
        status_code=(
            int(row["t0_status_code"]) if isinstance(row.get("t0_status_code"), int) else None
        ),
        final_url=row.get("t0_final_url"),
        content_type=row.get("t0_content_type"),
        content_hash=row.get("t0_content_hash"),
        etag=row.get("t0_etag"),
        last_modified=row.get("t0_last_modified"),
    )


async def _fetch_t1(client: httpx.AsyncClient, row: dict[str, Any]) -> Observation:
    url = str(row["fetch_url"])
    acquired_at = _now()
    try:
        parsed = validate_url_shape(url, source_name="M3 longitudinal t1")
        if parsed.hostname is None:
            raise HTTPException(status_code=422, detail="source host is missing")
        resolve_public_hostname(parsed.hostname, port=443, source_name="M3 longitudinal t1")
        async with client.stream("GET", url) as response:
            require_global_response_peer(response, source_name="M3 longitudinal t1")
            status = response.status_code
            content_type = response.headers.get("content-type")
            final_url = str(response.url)
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")
            if status == 304:
                return Observation(
                    source_id=str(row["source_id"]),
                    source_family=str(row["source_family"]),
                    fetch_url=url,
                    acquired_at=acquired_at,
                    status_code=304,
                    final_url=final_url,
                    content_type=content_type,
                    content_hash=None,
                    etag=etag,
                    last_modified=last_modified,
                )
            if 300 <= status < 400:
                return Observation(
                    source_id=str(row["source_id"]),
                    source_family=str(row["source_family"]),
                    fetch_url=url,
                    acquired_at=acquired_at,
                    status_code=status,
                    final_url=response.headers.get("location") or final_url,
                    content_type=content_type,
                    content_hash=None,
                    etag=etag,
                    last_modified=last_modified,
                )
            body = bytearray()
            async for chunk in response.aiter_raw():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    return Observation(
                        source_id=str(row["source_id"]),
                        source_family=str(row["source_family"]),
                        fetch_url=url,
                        acquired_at=acquired_at,
                        status_code=status,
                        final_url=final_url,
                        content_type=content_type,
                        content_hash=None,
                        etag=etag,
                        last_modified=last_modified,
                        error_type="oversize",
                    )
            digest = hashlib.sha256(bytes(body)).hexdigest() if status == 200 else None
            return Observation(
                source_id=str(row["source_id"]),
                source_family=str(row["source_family"]),
                fetch_url=url,
                acquired_at=acquired_at,
                status_code=status,
                final_url=final_url,
                content_type=content_type,
                content_hash=digest,
                etag=etag,
                last_modified=last_modified,
            )
    except HTTPException as exc:
        return Observation(
            source_id=str(row["source_id"]),
            source_family=str(row["source_family"]),
            fetch_url=url,
            acquired_at=acquired_at,
            status_code=exc.status_code,
            final_url=None,
            content_type=None,
            content_hash=None,
            etag=None,
            last_modified=None,
            error_type=str(exc.detail),
        )
    except httpx.TimeoutException:
        return Observation(
            source_id=str(row["source_id"]),
            source_family=str(row["source_family"]),
            fetch_url=url,
            acquired_at=acquired_at,
            status_code=None,
            final_url=None,
            content_type=None,
            content_hash=None,
            etag=None,
            last_modified=None,
            error_type="timeout",
        )
    except (httpx.HTTPError, OSError) as exc:
        return Observation(
            source_id=str(row["source_id"]),
            source_family=str(row["source_family"]),
            fetch_url=url,
            acquired_at=acquired_at,
            status_code=None,
            final_url=None,
            content_type=None,
            content_hash=None,
            etag=None,
            last_modified=None,
            error_type=type(exc).__name__,
        )


def _observation_payload(item: Observation) -> dict[str, Any]:
    return {
        "source_id": item.source_id,
        "source_family": item.source_family,
        "fetch_url": item.fetch_url,
        "acquired_at": item.acquired_at,
        "status_code": item.status_code,
        "final_url": item.final_url,
        "content_type": item.content_type,
        "content_hash": item.content_hash,
        "etag": item.etag,
        "last_modified": item.last_modified,
        "error_type": item.error_type,
    }


async def _collect_live(sample: list[dict[str, Any]], *, concurrency: int) -> list[Observation]:
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(row: dict[str, Any]) -> Observation:
        async with semaphore:
            return await _fetch_t1(client, row)

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "BulletFeed/longitudinal-t1"},
    ) as client:
        return list(await asyncio.gather(*(one(row) for row in sample)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args(argv)
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    sample = list(protocol["sample"])
    if args.live:
        t1_rows = asyncio.run(_collect_live(sample, concurrency=args.concurrency))
    else:
        t1_rows = [None] * len(sample)
    pairs = [(_t0_observation(row), second) for row, second in zip(sample, t1_rows, strict=True)]
    report = summarize_outcomes(pairs)
    report["protocol_version"] = PROTOCOL_VERSION
    report["live_collected"] = bool(args.live)
    report["pairs"] = [
        {
            "source_id": first.source_id,
            "source_family": first.source_family,
            "fetch_url": first.fetch_url,
            "outcome": classify_pair(first, second),
            "t0": _observation_payload(first),
            "t1": None if second is None else _observation_payload(second),
        }
        for first, second in pairs
    ]
    report["limitations"] = [
        "Live t1 is opt-in and is not part of ordinary PR CI.",
        "Response bodies are hashed in memory and not stored.",
        "A missing t1 is unavailable, never an update event.",
    ]
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
