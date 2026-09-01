"""G6 live shadow journal. Calendar days are not shortened."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

G6_POLICY = {
    "min_consecutive_days": 7,
    "min_live_sources": 100,
    "min_japanese_sources": 30,
    "min_families": 5,
    "min_observed_updates": 200,
    "acquisition_success": 0.99,
    "important_recall": 0.98,
    "silent_miss_max": 0,
    "stale_as_healthy_max": 0,
    "unclassified_max": 0,
}


def evaluate_g6_journal(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    days = payload.get("days") or []
    sources = payload.get("sources") or []
    updates = int(payload.get("observed_updates") or 0)
    started = payload.get("started_at")
    consecutive = 0
    if started and days:
        start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        expected = {(start + timedelta(days=offset)).date().isoformat() for offset in range(7)}
        have = {str(day.get("date")) for day in days}
        consecutive = len(expected & have)
    ja = sum(1 for source in sources if source.get("language") == "ja")
    families = {str(source.get("family")) for source in sources if source.get("family")}
    failures = []
    if consecutive < G6_POLICY["min_consecutive_days"]:
        failures.append("min_consecutive_days")
    if len(sources) < G6_POLICY["min_live_sources"]:
        failures.append("min_live_sources")
    if ja < G6_POLICY["min_japanese_sources"]:
        failures.append("min_japanese_sources")
    if len(families) < G6_POLICY["min_families"]:
        failures.append("min_families")
    if updates < G6_POLICY["min_observed_updates"]:
        failures.append("min_observed_updates")
    return {
        "policy": G6_POLICY,
        "consecutive_days": consecutive,
        "source_count": len(sources),
        "japanese_sources": ja,
        "family_count": len(families),
        "observed_updates": updates,
        "pass": not failures,
        "failures": failures,
        "status": "pass" if not failures else "calendar_or_capacity_unmet",
    }


def start_g6_journal(path: Path, *, sources: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload = {
        "journal_version": "product-gap-c1-g6-v1",
        "started_at": now.isoformat().replace("+00:00", "Z"),
        "sources": sources,
        "days": [{"date": now.date().isoformat(), "acquisition_ok": 0, "updates": 0}],
        "observed_updates": 0,
        "note": "Do not close Challenge 1 until 7 consecutive days and 200 updates are recorded.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
