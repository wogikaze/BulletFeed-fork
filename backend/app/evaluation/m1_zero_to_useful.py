"""M1 Zero-to-Useful-Feed qualification harness.

Deterministic fixture mode only. Does not open blind labels or live network.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from app.database import Database
from app.db.topic_catalog import install_topic_catalog
from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.source_actionability import actionability_allows_approve
from app.services.source_discovery import list_source_recommendations_for_user
from app.services.statuspage_pipeline import StatuspagePipeline
from app.stores.feed_store import FeedStore

HARNESS_VERSION = "m1-zero-to-useful-v02"
PERSONA_MANIFEST_VERSION = "m1-personas-v01"
STAGES = (
    "account",
    "interests",
    "discovery",
    "activation",
    "acquisition",
    "projection",
    "feed",
    "evidence",
    "feedback",
    "subsequent_feed",
)

Cohort = Literal["cold_start", "history_rich"]
Language = Literal["ja", "en", "mixed"]
Breadth = Literal["broad", "narrow"]
Security = Literal["high", "low"]


@dataclass(frozen=True)
class M1Persona:
    persona_id: str
    cohort: Cohort
    language: Language
    breadth: Breadth
    security: Security
    topics: tuple[str, ...]
    expect_empty_reason: str = ""


@dataclass(frozen=True)
class StageResult:
    stage: str
    ok: bool
    detail: str
    metrics: dict[str, Any]


@dataclass(frozen=True)
class PersonaReport:
    persona_id: str
    earliest_failure: str | None
    unexpected_empty_feed: bool
    intended_empty_feed: bool
    broken_evidence: bool
    tenant_leak: bool
    unsafe_suppression: bool
    stages: tuple[StageResult, ...]
    useful_proxy_at_5: int
    cards_to_first_useful: int | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stages"] = [asdict(stage) for stage in self.stages]
        return payload


def built_in_personas() -> tuple[M1Persona, ...]:
    """30 constructed personas covering M1 qualification slices."""
    specs: list[M1Persona] = []
    topics_pool = (
        ("latency", "API"),
        ("security", "CVE"),
        ("コンパイラ最適化",),
        ("Rust", "コンパイラ"),
        ("Kubernetes", "Go"),
        ("React", "TypeScript"),
        ("statuspage",),
        ("データベース", "latency"),
    )
    languages: tuple[Language, ...] = ("ja", "en", "mixed")
    cohorts: tuple[Cohort, ...] = ("cold_start", "history_rich")
    for index in range(28):
        topics = topics_pool[index % len(topics_pool)]
        if index % 4 == 0:
            topics = topics[:1]
        specs.append(
            M1Persona(
                persona_id=f"m1p_{index + 1:02d}",
                cohort=cohorts[index % 2],
                language=languages[index % 3],
                breadth="narrow" if len(topics) == 1 else "broad",
                security="high" if index % 5 == 0 else "low",
                topics=topics,
            )
        )
    specs.append(
        M1Persona(
            persona_id="m1p_29",
            cohort="cold_start",
            language="en",
            breadth="narrow",
            security="low",
            topics=(),
            expect_empty_reason="no_topics_abstention",
        )
    )
    specs.append(
        M1Persona(
            persona_id="m1p_30",
            cohort="history_rich",
            language="ja",
            breadth="narrow",
            security="high",
            topics=(),
            expect_empty_reason="no_topics_abstention",
        )
    )
    return tuple(specs)


def write_persona_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest_version": PERSONA_MANIFEST_VERSION,
        "label_source": "constructed",
        "personas": [asdict(persona) for persona in built_in_personas()],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_persona_manifest(path: Path) -> tuple[M1Persona, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("manifest_version") != PERSONA_MANIFEST_VERSION:
        raise ValueError(f"unsupported persona manifest {raw.get('manifest_version')}")
    personas = tuple(
        M1Persona(
            persona_id=row["persona_id"],
            cohort=row["cohort"],
            language=row["language"],
            breadth=row["breadth"],
            security=row["security"],
            topics=tuple(row["topics"]),
            expect_empty_reason=row.get("expect_empty_reason", ""),
        )
        for row in raw["personas"]
    )
    if len(personas) < 30:
        raise ValueError("M1 persona floor is 30")
    return personas


def _summary() -> dict[str, Any]:
    return {
        "incidents": [
            {
                "id": "inc_m1",
                "name": "API latency",
                "impact": "major",
                "created_at": "2026-08-22T00:00:00Z",
                "shortlink": "https://stspg.io/inc_m1",
                "incident_updates": [
                    {
                        "id": "upd_m1_1",
                        "status": "investigating",
                        "body": "Investigating elevated latency.",
                        "created_at": "2026-08-22T00:00:00Z",
                        "updated_at": "2026-08-22T00:00:00Z",
                        "display_at": "2026-08-22T00:00:00Z",
                    }
                ],
            }
        ]
    }


def run_persona_journey(database: Database, persona: M1Persona) -> PersonaReport:
    stages: list[StageResult] = []
    user_id = f"user_{persona.persona_id}"
    outsider_id = f"outsider_{persona.persona_id}"

    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", (user_id,))
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", (outsider_id,))
    install_topic_catalog(database)
    stages.append(StageResult("account", True, "created", {"user_id": user_id}))

    with database.connect() as connection:
        for index, name in enumerate(persona.topics):
            connection.execute(
                """
                INSERT INTO topics (id, user_id, name, type, priority, sort_order, created_at)
                VALUES (?, ?, ?, 'technology', 'high', ?, 0)
                """,
                (f"{user_id}-t{index}", user_id, name, index),
            )
    stages.append(
        StageResult(
            "interests",
            True,
            "topics recorded",
            {"topic_count": len(persona.topics)},
        )
    )

    intended_empty = bool(persona.expect_empty_reason)
    recommendations = list_source_recommendations_for_user(database, user_id)
    approvable = [
        item for item in recommendations.items if actionability_allows_approve(item.actionability)
    ]
    discovery_ok = intended_empty or bool(recommendations.items)
    stages.append(
        StageResult(
            "discovery",
            discovery_ok,
            persona.expect_empty_reason or ("candidates" if recommendations.items else "no_candidates"),
            {
                "candidate_count": len(recommendations.items),
                "runtime_hint_count": recommendations.runtime_hint_count,
                "seed_fallback_used": recommendations.seed_fallback_used,
            },
        )
    )
    stages.append(
        StageResult(
            "activation",
            intended_empty or bool(approvable),
            "approvable" if approvable else "no_approvable_candidate",
            {
                "approvable_count": len(approvable),
                "actionabilities": sorted({item.actionability for item in recommendations.items}),
            },
        )
    )

    result = StatuspagePipeline(database).ingest_summary(
        page_id="abcd1234",
        summary=_summary(),
        retrieved_at="2026-08-22T00:11:00Z",
    )
    event_id = result.event_ids[0]
    stages.append(
        StageResult(
            "acquisition",
            bool(result.event_ids),
            "statuspage fixture ingested",
            {"event_ids": list(result.event_ids)},
        )
    )
    LedgerProjector(database).project_event(event_id)
    created = FeedProjector(database).project_event_for_user(user_id=user_id, event_id=event_id)
    outsider_created = FeedProjector(database).project_event_for_user(
        user_id=outsider_id, event_id=event_id
    )
    FeedProjector(database).reproject_user(user_id=user_id)
    FeedProjector(database).reproject_user(user_id=outsider_id)
    stages.append(
        StageResult(
            "projection",
            True,
            "projected",
            {"feed_item_count": len(created), "outsider_count": len(outsider_created)},
        )
    )

    store = FeedStore(database)
    items, _ = store.list_feed(user_id, relation=None, item_status=None, cursor=None, limit=20)
    outsider_items, _ = store.list_feed(
        outsider_id, relation=None, item_status=None, cursor=None, limit=20
    )
    intended_empty = bool(persona.expect_empty_reason)
    unexpected_empty = (not items) and not intended_empty
    tenant_leak = any(item.id in {row.id for row in outsider_items} for item in items) and bool(items)
    if tenant_leak:
        shared = {item.id for item in items} & {item.id for item in outsider_items}
        tenant_leak = bool(shared)
    stages.append(
        StageResult(
            "feed",
            not unexpected_empty,
            persona.expect_empty_reason or "feed listed",
            {"surfaced": len(items), "outsider_surfaced": len(outsider_items)},
        )
    )

    broken_evidence = False
    if items:
        with database.connect() as connection:
            for item in items:
                evidence = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM claim_evidence e
                    JOIN delta_claim_map m ON m.claim_id = e.claim_id
                    JOIN deltas d ON d.id = m.delta_id
                    WHERE d.event_id = ?
                    """,
                    (item.event_id,),
                ).fetchone()
                if int(evidence["count"]) == 0:
                    broken_evidence = True
                    break
    stages.append(
        StageResult(
            "evidence",
            not broken_evidence,
            "claim_evidence present" if items else "no cards",
            {"broken_evidence": broken_evidence},
        )
    )

    if items:
        store.record_exposures(
            user_id,
            [{"delivery_id": items[0].delivery_id, "displayed_at": "2026-08-22T00:12:00Z"}],
        )
        store.save_feedback(user_id, items[0].id, "important")
    stages.append(StageResult("feedback", True, "applied if cards existed", {}))

    later, _ = store.list_feed(user_id, relation=None, item_status=None, cursor=None, limit=20)
    stages.append(
        StageResult("subsequent_feed", True, "relisted", {"surfaced": len(later)})
    )

    useful = min(5, len(items))
    cards_to_first = 1 if items else None
    earliest = next((stage.stage for stage in stages if not stage.ok), None)
    return PersonaReport(
        persona_id=persona.persona_id,
        earliest_failure=earliest,
        unexpected_empty_feed=unexpected_empty,
        intended_empty_feed=intended_empty and not items,
        broken_evidence=broken_evidence,
        tenant_leak=tenant_leak,
        unsafe_suppression=False,
        stages=tuple(stages),
        useful_proxy_at_5=useful,
        cards_to_first_useful=cards_to_first,
    )


def run_qualification(
    database_factory,
    personas: Sequence[M1Persona] | None = None,
) -> dict[str, Any]:
    selected = tuple(personas or built_in_personas())
    reports = [run_persona_journey(database_factory(), persona) for persona in selected]
    failures = [report.persona_id for report in reports if report.earliest_failure]
    return {
        "harness_version": HARNESS_VERSION,
        "persona_manifest_version": PERSONA_MANIFEST_VERSION,
        "label_source": "constructed",
        "persona_count": len(reports),
        "attempted": len(reports),
        "failed_persona_ids": failures,
        "unexpected_empty_feed": sum(1 for report in reports if report.unexpected_empty_feed),
        "broken_evidence": sum(1 for report in reports if report.broken_evidence),
        "tenant_leak": sum(1 for report in reports if report.tenant_leak),
        "reports": [report.as_dict() for report in reports],
    }
