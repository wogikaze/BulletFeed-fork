"""Seeded in-process load profile for M5 #169.

Measures ingest, feed list, ranking, and health under a constructed Statuspage
corpus. Does not use live network. Blind labels are not consulted.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.database import Database
from app.db.release_lifecycle import record_worker_heartbeat
from app.observability import counters, reset
from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore

PROFILE_VERSION = "seeded-load-v2"
REMEDIATIONS = (
    "idx_feed_items_user_dismissed",
    "batched_claim_knowledge_ids",
    "defer_feedback_ranking_until_user_batch",
)


@dataclass(frozen=True)
class StageTiming:
    name: str
    elapsed_ms: float
    items: int


@dataclass(frozen=True)
class SeededLoadReport:
    version: str
    incident_count: int
    updates_per_incident: int
    user_count: int
    projected_item_count: int
    stages: tuple[StageTiming, ...]
    counters: dict[str, int]
    bottlenecks: tuple[str, ...]
    remediations: tuple[str, ...] = REMEDIATIONS

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "incidentCount": self.incident_count,
            "updatesPerIncident": self.updates_per_incident,
            "userCount": self.user_count,
            "projectedItemCount": self.projected_item_count,
            "stages": [asdict(stage) for stage in self.stages],
            "counters": self.counters,
            "bottlenecks": list(self.bottlenecks),
            "remediations": list(self.remediations),
        }


def _summary(*, incidents: int, updates: int) -> dict[str, Any]:
    items = []
    for index in range(incidents):
        incident_id = f"inc_load_{index:04d}"
        incident_updates = []
        for step in range(updates):
            occurred = f"2026-08-{(step % 28) + 1:02d}T00:{step:02d}:00Z"
            incident_updates.append(
                {
                    "id": f"upd_{incident_id}_{step}",
                    "status": "identified" if step else "investigating",
                    "body": f"Load incident {index} update {step}.",
                    "created_at": occurred,
                    "updated_at": occurred,
                    "display_at": occurred,
                }
            )
        items.append(
            {
                "id": incident_id,
                "name": f"API latency {index}",
                "impact": "major",
                "created_at": "2026-08-01T00:00:00Z",
                "shortlink": f"https://stspg.io/{incident_id}",
                "incident_updates": incident_updates,
            }
        )
    return {"incidents": items}


def _time_stage(name: str, items: int, work) -> StageTiming:
    started = time.perf_counter()
    work()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return StageTiming(name=name, elapsed_ms=round(elapsed_ms, 3), items=items)


def _bottlenecks(stages: tuple[StageTiming, ...], *, top_n: int = 3) -> tuple[str, ...]:
    ranked = sorted(stages, key=lambda stage: stage.elapsed_ms, reverse=True)
    return tuple(stage.name for stage in ranked[:top_n] if stage.elapsed_ms > 0)


def run_seeded_load_profile(
    database: Database,
    *,
    incident_count: int = 40,
    updates_per_incident: int = 4,
    user_count: int = 3,
) -> SeededLoadReport:
    reset()
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    users = [f"usr_load_{index}" for index in range(user_count)]
    with database.connect() as connection:
        for user_id in users:
            connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)", (user_id,))
        connection.commit()

    pipeline = StatuspagePipeline(database)
    projector = LedgerProjector(database)
    feed = FeedProjector(database)
    store = FeedStore(database)
    summary = _summary(incidents=incident_count, updates=updates_per_incident)

    ingest_holder: dict[str, Any] = {}

    def _ingest() -> None:
        ingest_holder["result"] = pipeline.ingest_summary(
            page_id="loadpage1",
            summary=summary,
            retrieved_at=retrieved_at,
        )

    ingest_stage = _time_stage("statuspage_ingest", incident_count * updates_per_incident, _ingest)
    result = ingest_holder["result"]

    def _project_ledger() -> None:
        for event_id in result.event_ids:
            projector.project_event(event_id)

    ledger_stage = _time_stage("ledger_projection", len(result.event_ids), _project_ledger)
    projected = 0

    def _project_feed() -> None:
        nonlocal projected
        for user_id in users:
            projected += len(
                feed.project_events_for_user(user_id=user_id, event_ids=result.event_ids)
            )

    feed_stage = _time_stage("feed_projection", len(users) * len(result.event_ids), _project_feed)

    def _list_feed() -> None:
        for user_id in users:
            store.list_feed(user_id, relation=None, item_status=None, cursor=None, limit=20)

    list_stage = _time_stage("feed_list", user_count, _list_feed)

    def _heartbeat() -> None:
        record_worker_heartbeat(database, detail="seeded-load")

    ready_stage = _time_stage("worker_heartbeat", 1, _heartbeat)
    stages = (ingest_stage, ledger_stage, feed_stage, list_stage, ready_stage)
    return SeededLoadReport(
        version=PROFILE_VERSION,
        incident_count=incident_count,
        updates_per_incident=updates_per_incident,
        user_count=user_count,
        projected_item_count=projected,
        stages=stages,
        counters=counters(),
        bottlenecks=_bottlenecks(stages),
        remediations=REMEDIATIONS,
    )


def compare_load_reports(before: SeededLoadReport, after: SeededLoadReport) -> dict[str, Any]:
    before_ms = {stage.name: stage.elapsed_ms for stage in before.stages}
    after_ms = {stage.name: stage.elapsed_ms for stage in after.stages}
    deltas = {
        name: round(after_ms.get(name, 0.0) - before_ms.get(name, 0.0), 3)
        for name in sorted(set(before_ms) | set(after_ms))
    }
    return {
        "beforeVersion": before.version,
        "afterVersion": after.version,
        "stageDeltasMs": deltas,
        "sharedBottlenecks": [
            name for name in after.bottlenecks if name in before.bottlenecks
        ],
    }


def write_report(report: SeededLoadReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
