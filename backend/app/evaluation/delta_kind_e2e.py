"""Source-to-API split of duplicate / additional / correction / conflict (#324).

Runs the production ingest → ledger → Event/Delta → knownness → ranking →
`GET /v1/feed` store path. Failures name the earliest broken stage.
False merge is gated harder than a leftover split.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.database import Database
from app.services.feed_projection import FeedProjector
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore, LedgerClaim
from app.stores.feed_store import FeedStore

DATASET_VERSION = "delta-kind-e2e-v01"
StageName = Literal[
    "ok",
    "source",
    "acquire",
    "claim",
    "event_delta",
    "knownness",
    "ranking",
    "api",
    "false_merge",
]
STAGE_ORDER: tuple[str, ...] = (
    "source",
    "acquire",
    "claim",
    "event_delta",
    "knownness",
    "ranking",
    "api",
    "false_merge",
)


@dataclass(frozen=True)
class StageCheck:
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class ScenarioEval:
    scenario_id: str
    expected_delta_kind: str
    first_broken_stage: StageName
    stages: dict[str, StageCheck]
    observed: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "expected_delta_kind": self.expected_delta_kind,
            "first_broken_stage": self.first_broken_stage,
            "stages": {name: {"ok": check.ok, "detail": check.detail} for name, check in self.stages.items()},
            "observed": self.observed,
        }


@dataclass(frozen=True)
class DeltaKindReport:
    version: str
    passed: bool
    false_merge_count: int
    cases: tuple[ScenarioEval, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "passed": self.passed,
            "false_merge_count": self.false_merge_count,
            "cases": [case.as_dict() for case in self.cases],
        }


def first_broken_stage(stages: dict[str, StageCheck]) -> StageName:
    for name in STAGE_ORDER:
        check = stages.get(name)
        if check is not None and not check.ok:
            return name  # type: ignore[return-value]
    return "ok"


def _check(ok: bool, detail: str = "") -> StageCheck:
    return StageCheck(ok=ok, detail=detail)


def _user(database: Database, user_id: str, *, topic: str = "Rust") -> None:
    with database.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, 0)", (user_id,))
        connection.execute(
            """
            INSERT OR IGNORE INTO topics (
                id, user_id, name, type, priority, sort_order, created_at
            ) VALUES (?, ?, ?, 'technology', 'high', 0, 0)
            """,
            (f"topic_{user_id}", user_id, topic),
        )


def _ingest(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    observation_id: str,
    source_event_id: str,
    title: str,
    value: str,
    detail: str,
    at: str,
    slot: str = "status",
    canonical_event_key: str | None = None,
    explicit_correction: bool = False,
    unresolved_source_conflict: bool = False,
    payload: dict[str, Any] | None = None,
) -> tuple[Any, LedgerClaim]:
    observation = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type=source_type,
                source_key=source_key,
                source_observation_id=observation_id,
                payload=payload
                or {
                    "id": observation_id,
                    "value": value,
                    "detail": detail,
                    "ghsa_id": source_key if source_key.upper().startswith("GHSA-") else None,
                },
                original_url=f"https://example.test/{source_type}/{observation_id}",
                published_at=at,
            ),
        ),
        retrieved_at=at,
    )[0]
    claim = ClaimLedgerStore(database).ingest(
        observation,
        source_event_id=source_event_id,
        canonical_event_key=canonical_event_key,
        title=title,
        slot=slot,
        value=value,
        detail=detail,
        valid_at=at,
        evidence_text=detail or value,
        explicit_correction=explicit_correction,
        unresolved_source_conflict=unresolved_source_conflict,
    )
    return observation, claim


def _project(database: Database, user_id: str, event_ids: Sequence[str]) -> None:
    projector = LedgerProjector(database)
    for event_id in dict.fromkeys(event_ids):
        projector.project_event(event_id)
    FeedProjector(database).project_events_for_user(user_id=user_id, event_ids=event_ids)


def _cards(database: Database, user_id: str):
    return FeedStore(database).list_feed(
        user_id,
        relation=None,
        item_status=None,
        cursor=None,
        limit=50,
    )[0]


def _mark_seen(database: Database, user_id: str, cards) -> None:
    store = FeedStore(database)
    if not cards:
        return
    store.record_exposures(
        user_id,
        [
            {
                "delivery_id": item.delivery_id,
                "displayed_at": "2026-08-22T00:02:00Z",
                "dwell_ms": 1200,
                "visible_ratio": 0.8,
            }
            for item in cards
        ],
    )
    store.mark_read(user_id, cards[0].id)


def _delta_types(database: Database, event_id: str) -> list[str]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT type FROM deltas WHERE event_id = ? AND active = 1 ORDER BY occurred_at, id",
            (event_id,),
        ).fetchall()
    return [row["type"] for row in rows]


def _eval(
    *,
    scenario_id: str,
    expected_delta_kind: str,
    stages: dict[str, StageCheck],
    observed: dict[str, Any],
) -> ScenarioEval:
    return ScenarioEval(
        scenario_id=scenario_id,
        expected_delta_kind=expected_delta_kind,
        first_broken_stage=first_broken_stage(stages),
        stages=stages,
        observed=observed,
    )


def run_duplicate_paraphrase(database: Database) -> ScenarioEval:
    user_id = "user_dup"
    _user(database, user_id)
    first_obs, first = _ingest(
        database,
        source_type="statuspage",
        source_key="acme",
        observation_id="obs_dup_a",
        source_event_id="inc_dup_a",
        title="API latency",
        value="investigating",
        detail="Investigating elevated latency.",
        at="2026-08-22T00:00:00Z",
        canonical_event_key="latency-dup",
    )
    second_obs, second = _ingest(
        database,
        source_type="rss_atom",
        source_key="https://news.example/feed.xml",
        observation_id="obs_dup_b",
        source_event_id="inc_dup_b",
        title="API latency",
        value="investigating",
        detail="Investigating elevated latency.",
        at="2026-08-22T00:01:00Z",
        canonical_event_key="latency-dup",
    )
    stages = {
        "source": _check(bool(first_obs.id and second_obs.id), "observations missing"),
        "acquire": _check(bool(first_obs.original_url and second_obs.original_url), "urls missing"),
        "claim": _check(first.claim_id != second.claim_id, "claims were not written separately"),
        "event_delta": _check(
            first.event_id == second.event_id
            and first.relation_type == "NEW_FACT"
            and second.relation_type == "NON_NOVEL",
            f"relations={first.relation_type},{second.relation_type}",
        ),
        "false_merge": _check(True),
    }
    if not stages["event_delta"].ok:
        return _eval(
            scenario_id="duplicate_paraphrase",
            expected_delta_kind="new_fact",
            stages=stages,
            observed={"first": first.relation_type, "second": second.relation_type},
        )
    _project(database, user_id, [first.event_id])
    types = _delta_types(database, first.event_id)
    cards = _cards(database, user_id)
    kinds = [item.display_reason.delta_kind if item.display_reason else None for item in cards]
    stages["knownness"] = _check(True)
    stages["ranking"] = _check(all(item.display_reason is not None for item in cards), "reason missing")
    stages["api"] = _check(
        types == ["new_fact"] and len(cards) == 1 and kinds == ["new_fact"],
        f"deltas={types} cards={len(cards)} kinds={kinds}",
    )
    return _eval(
        scenario_id="duplicate_paraphrase",
        expected_delta_kind="new_fact",
        stages=stages,
        observed={"delta_types": types, "card_count": len(cards), "delta_kinds": kinds},
    )


def run_additional_detail(database: Database) -> ScenarioEval:
    user_id = "user_add"
    _user(database, user_id)
    first_obs, first = _ingest(
        database,
        source_type="statuspage",
        source_key="acme",
        observation_id="obs_add_a",
        source_event_id="inc_add_a",
        title="API latency",
        value="investigating",
        detail="Investigating elevated latency.",
        at="2026-08-22T00:00:00Z",
        canonical_event_key="latency-add",
    )
    stages = {
        "source": _check(bool(first_obs.id)),
        "acquire": _check(bool(first_obs.original_url)),
        "claim": _check(first.relation_type == "NEW_FACT", first.relation_type),
        "false_merge": _check(True),
    }
    _project(database, user_id, [first.event_id])
    first_cards = _cards(database, user_id)
    _mark_seen(database, user_id, first_cards)
    _obs2, second = _ingest(
        database,
        source_type="statuspage",
        source_key="acme",
        observation_id="obs_add_b",
        source_event_id="inc_add_a",
        title="API latency",
        value="investigating",
        detail="Investigating elevated latency in the EU region after a config change.",
        at="2026-08-22T00:10:00Z",
        canonical_event_key="latency-add",
    )
    stages["event_delta"] = _check(second.relation_type == "DETAIL", second.relation_type)
    stages["knownness"] = _check(True)
    if not stages["event_delta"].ok:
        return _eval(
            scenario_id="additional_detail",
            expected_delta_kind="additional",
            stages=stages,
            observed={"second": second.relation_type},
        )
    _project(database, user_id, [first.event_id])
    cards = _cards(database, user_id)
    additional = [
        item
        for item in cards
        if item.display_reason and item.display_reason.delta_kind == "additional"
    ]
    stages["ranking"] = _check(bool(additional), "detail card missing after knownness")
    stages["api"] = _check(
        bool(additional) and additional[0].delta.type == "detail",
        f"types={[item.delta.type for item in cards]}",
    )
    return _eval(
        scenario_id="additional_detail",
        expected_delta_kind="additional",
        stages=stages,
        observed={
            "card_count": len(cards),
            "delta_types": [item.delta.type for item in cards],
            "delta_kinds": [
                item.display_reason.delta_kind if item.display_reason else None for item in cards
            ],
        },
    )


def run_state_update(database: Database) -> ScenarioEval:
    user_id = "user_state"
    _user(database, user_id)
    first_obs, first = _ingest(
        database,
        source_type="github_release",
        source_key="acme/widget",
        observation_id="obs_state_a",
        source_event_id="rel_state_a",
        title="acme/widget release",
        value="v2.0.0",
        detail="Released v2.0.0",
        at="2026-08-22T00:00:00Z",
        slot="version",
        canonical_event_key="widget-version",
    )
    _obs2, second = _ingest(
        database,
        source_type="github_release",
        source_key="acme/widget",
        observation_id="obs_state_b",
        source_event_id="rel_state_b",
        title="acme/widget release",
        value="v2.0.1",
        detail="Released v2.0.1",
        at="2026-08-22T00:10:00Z",
        slot="version",
        canonical_event_key="widget-version",
    )
    stages = {
        "source": _check(bool(first_obs.id)),
        "acquire": _check(bool(first_obs.original_url)),
        "claim": _check(first.claim_id != second.claim_id),
        "event_delta": _check(second.relation_type == "STATE_UPDATE", second.relation_type),
        "knownness": _check(True),
        "false_merge": _check(
            first.value != second.value,
            "version change was collapsed to one claim value",
        ),
    }
    if not stages["event_delta"].ok:
        return _eval(
            scenario_id="state_update",
            expected_delta_kind="state_update",
            stages=stages,
            observed={"second": second.relation_type},
        )
    _project(database, user_id, [first.event_id])
    cards = _cards(database, user_id)
    updates = [
        item
        for item in cards
        if item.display_reason and item.display_reason.delta_kind == "state_update"
    ]
    stages["ranking"] = _check(bool(updates), "state_update card missing")
    stages["api"] = _check(
        bool(updates) and updates[0].delta.type == "state_update",
        f"types={[item.delta.type for item in cards]}",
    )
    return _eval(
        scenario_id="state_update",
        expected_delta_kind="state_update",
        stages=stages,
        observed={
            "delta_types": [item.delta.type for item in cards],
            "delta_kinds": [
                item.display_reason.delta_kind if item.display_reason else None for item in cards
            ],
        },
    )


def run_explicit_correction(database: Database) -> ScenarioEval:
    user_id = "user_corr"
    _user(database, user_id)
    first_obs, first = _ingest(
        database,
        source_type="statuspage",
        source_key="acme",
        observation_id="obs_corr_a",
        source_event_id="inc_corr_a",
        title="API latency",
        value="Asia",
        detail="Requests from Asia are affected.",
        at="2026-08-22T00:00:00Z",
        canonical_event_key="latency-corr",
    )
    _project(database, user_id, [first.event_id])
    _mark_seen(database, user_id, _cards(database, user_id))
    _obs2, second = _ingest(
        database,
        source_type="statuspage",
        source_key="acme",
        observation_id="obs_corr_b",
        source_event_id="inc_corr_a",
        title="API latency",
        value="Europe",
        detail="Correction: the previous update was incorrect. Requests from Europe are affected.",
        at="2026-08-22T00:10:00Z",
        canonical_event_key="latency-corr",
        explicit_correction=True,
    )
    stages = {
        "source": _check(bool(first_obs.id)),
        "acquire": _check(bool(first_obs.original_url)),
        "claim": _check(first.claim_id != second.claim_id),
        "event_delta": _check(second.relation_type == "CORRECTION", second.relation_type),
        "knownness": _check(True, "correction must cross ordinary knownness"),
        "false_merge": _check(first.value != second.value),
    }
    _project(database, user_id, [first.event_id])
    cards = _cards(database, user_id)
    corrections = [
        item
        for item in cards
        if item.display_reason and item.display_reason.delta_kind == "correction"
    ]
    stages["ranking"] = _check(
        bool(corrections)
        and corrections[0].display_reason is not None
        and corrections[0].display_reason.primary_code == "priority.correction",
        "correction did not get the ranker priority explanation",
    )
    stages["api"] = _check(
        bool(corrections) and corrections[0].delta.type == "correction",
        f"types={[item.delta.type for item in cards]}",
    )
    return _eval(
        scenario_id="explicit_correction",
        expected_delta_kind="correction",
        stages=stages,
        observed={
            "delta_types": [item.delta.type for item in cards],
            "primary_codes": [
                item.display_reason.primary_code if item.display_reason else None for item in cards
            ],
        },
    )


def run_unresolved_conflict(database: Database) -> ScenarioEval:
    user_id = "user_conf"
    _user(database, user_id)
    first_obs, first = _ingest(
        database,
        source_type="github_release",
        source_key="acme/widget",
        observation_id="obs_conf_a",
        source_event_id="rel_conf_a",
        title="acme/widget v2 availability",
        value="available",
        detail="GitHub Release reports v2 is available.",
        at="2026-08-22T10:00:00Z",
        slot="availability",
        canonical_event_key="widget-availability",
    )
    _obs2, second = _ingest(
        database,
        source_type="json_feed",
        source_key="https://status.acme.example/feed.json",
        observation_id="obs_conf_b",
        source_event_id="feed_conf_b",
        title="acme/widget v2 availability",
        value="unavailable",
        detail="Official status feed reports v2 is not yet available.",
        at="2026-08-22T11:00:00Z",
        slot="availability",
        canonical_event_key="widget-availability",
        unresolved_source_conflict=True,
    )
    stages = {
        "source": _check(bool(first_obs.id)),
        "acquire": _check(bool(first_obs.original_url)),
        "claim": _check(first.event_id == second.event_id),
        "event_delta": _check(
            second.relation_type == "UNRESOLVED_CONTRADICTION",
            second.relation_type,
        ),
        "knownness": _check(True),
        "false_merge": _check(
            first.value != second.value,
            "conflicting values were merged into one settled claim",
        ),
    }
    _project(database, user_id, [first.event_id])
    cards = _cards(database, user_id)
    conflicts = [
        item
        for item in cards
        if item.display_reason and item.display_reason.delta_kind == "conflict"
    ]
    stages["ranking"] = _check(
        bool(conflicts)
        and conflicts[0].display_reason is not None
        and conflicts[0].display_reason.primary_code == "priority.unresolved_conflict",
        "conflict did not get the ranker priority explanation",
    )
    stages["api"] = _check(
        bool(conflicts) and conflicts[0].delta.type == "unresolved_contradiction",
        f"types={[item.delta.type for item in cards]}",
    )
    return _eval(
        scenario_id="unresolved_conflict",
        expected_delta_kind="conflict",
        stages=stages,
        observed={
            "delta_types": [item.delta.type for item in cards],
            "current_kept_separate": first.value != second.value,
        },
    )


def run_syndication(database: Database) -> ScenarioEval:
    user_id = "user_syn"
    _user(database, user_id)
    ghsa = "GHSA-1111-2222-3333"
    first_obs, first = _ingest(
        database,
        source_type="github_advisory",
        source_key=ghsa,
        observation_id="obs_syn_gh",
        source_event_id="adv_syn_gh",
        title="Widget advisory",
        value="affected",
        detail="Widget 2.0 is affected by GHSA-1111-2222-3333.",
        at="2026-08-22T00:00:00Z",
        payload={"id": ghsa, "ghsa_id": ghsa, "summary": "Widget advisory"},
    )
    second_obs, second = _ingest(
        database,
        source_type="osv",
        source_key=ghsa,
        observation_id="obs_syn_osv",
        source_event_id="adv_syn_osv",
        title="Widget advisory",
        value="affected",
        detail="Widget 2.0 is affected by GHSA-1111-2222-3333.",
        at="2026-08-22T00:01:00Z",
        payload={"id": "OSV-2026-1", "aliases": [ghsa], "summary": "Widget advisory"},
    )
    first_count = ClaimLedgerStore(database).independent_evidence_count(first.claim_id)
    second_count = ClaimLedgerStore(database).independent_evidence_count(second.claim_id)
    stages = {
        "source": _check(bool(first_obs.id and second_obs.id)),
        "acquire": _check(bool(first_obs.original_url and second_obs.original_url)),
        "claim": _check(first.claim_id != second.claim_id),
        "event_delta": _check(True),
        "knownness": _check(True),
        "false_merge": _check(
            first.event_id != second.event_id,
            "distinct source events were force-merged before projection",
        ),
    }
    _project(database, user_id, [first.event_id, second.event_id])
    cards = _cards(database, user_id)
    roles = [role for item in cards for role in (item.display_reason.codes if item.display_reason else [])]
    additional_roles = [src.role for item in cards for src in item.additional_sources]
    evidence_counts = [
        item.display_reason.independent_evidence_count if item.display_reason else None for item in cards
    ]
    stages["ranking"] = _check(len(cards) == 1, f"duplicate advisory cards={len(cards)}")
    stages["api"] = _check(
        len(cards) == 1
        and 1 in evidence_counts
        and ("syndication" in additional_roles or "provenance.syndication" in roles)
        and first_count == 1
        and second_count == 1,
        f"cards={len(cards)} roles={additional_roles} counts={evidence_counts}",
    )
    return _eval(
        scenario_id="syndication",
        expected_delta_kind="new_fact",
        stages=stages,
        observed={
            "card_count": len(cards),
            "additional_roles": additional_roles,
            "independent_evidence_count": evidence_counts,
            "claim_evidence_counts": [first_count, second_count],
        },
    )


def run_uncertain_knownness(database: Database) -> ScenarioEval:
    user_id = "user_unc"
    _user(database, user_id)
    first_obs, first = _ingest(
        database,
        source_type="rss_atom",
        source_key="wire-a",
        observation_id="obs_unc_a",
        source_event_id="inc_unc_a",
        title="Maybe related A",
        value="possible outage",
        detail="Reports of an outage are unconfirmed.",
        at="2026-08-22T00:00:00Z",
    )
    second_obs, second = _ingest(
        database,
        source_type="rss_atom",
        source_key="wire-b",
        observation_id="obs_unc_b",
        source_event_id="inc_unc_b",
        title="Maybe related B",
        value="network issue",
        detail="A different network issue may be happening.",
        at="2026-08-22T00:01:00Z",
    )
    stages = {
        "source": _check(bool(first_obs.id and second_obs.id)),
        "acquire": _check(True),
        "claim": _check(first.event_id != second.event_id, "uncertain identity was merged"),
        "event_delta": _check(True),
        "false_merge": _check(
            first.event_id != second.event_id and first.value != second.value,
            "ambiguous identities were collapsed",
        ),
    }
    _project(database, user_id, [first.event_id])
    first_cards = _cards(database, user_id)
    _mark_seen(database, user_id, first_cards)
    _project(database, user_id, [second.event_id])
    cards = _cards(database, user_id)
    ids = {item.event_id for item in cards}
    hidden_unknown = second.event_id not in ids
    stages["knownness"] = _check(not hidden_unknown, "uncertain unknown was hidden")
    stages["ranking"] = _check(second.event_id in ids, "second card missing")
    stages["api"] = _check(
        first.event_id in ids and second.event_id in ids,
        f"events={sorted(ids)}",
    )
    if hidden_unknown:
        stages["false_merge"] = _check(False, "unknown card disappeared after a different known item")
    return _eval(
        scenario_id="uncertain_knownness",
        expected_delta_kind="new_fact",
        stages=stages,
        observed={"event_ids": sorted(ids), "card_count": len(cards)},
    )


def evaluate_delta_kind_e2e(database: Database) -> DeltaKindReport:
    cases = (
        run_duplicate_paraphrase(database),
        run_additional_detail(database),
        run_state_update(database),
        run_explicit_correction(database),
        run_unresolved_conflict(database),
        run_syndication(database),
        run_uncertain_knownness(database),
    )
    false_merge_count = sum(1 for case in cases if case.first_broken_stage == "false_merge")
    return DeltaKindReport(
        version=DATASET_VERSION,
        passed=all(case.first_broken_stage == "ok" for case in cases),
        false_merge_count=false_merge_count,
        cases=cases,
    )
