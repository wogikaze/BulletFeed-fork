import json
from pathlib import Path

from app.services.event_identity_repair import EventIdentityRepairService
from app.services.feedback_signals import (
    assert_feedback_does_not_mutate_ledger,
    ledger_world_state,
)
from app.services.feed_projection import FeedProjector
from app.services.knowledge_evidence import (
    KIND_ALREADY_KNEW,
    KIND_DELIVERED,
    STATE_KNOWN,
    STATE_UNKNOWN,
    append_knowledge_evidence,
    list_knowledge_evidence,
    may_hide,
    replay_knowledge_state,
)
from app.services.knowledge_identity import (
    KNOWLEDGE_IDENTITY_VERSION,
    compare_knowledge_identity,
    ensure_claim_knowledge_mapping,
    fingerprint_claim,
    identity_may_hide,
    list_knowledge_evidence_for_identity,
    rebuild_knowledge_identities,
    replay_knowledge_state_for_identity,
    resolve_claim_knowledge_id,
    visibility_for_identity,
)
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore
from app.stores.feed_store import FeedStore

_GOLD = json.loads(
    (Path(__file__).parent / "gold" / "knowledge_identity_v01.json").read_text(encoding="utf-8")
)


def _ingest_claim(
    database,
    *,
    source_type: str,
    source_key: str,
    observation_id: str,
    source_event_id: str,
    title: str,
    value: str,
    detail: str,
    at: str,
    slot: str = "state",
    canonical_event_key: str | None = None,
):
    observation = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type=source_type,
                source_key=source_key,
                source_observation_id=observation_id,
                payload={"value": value, "detail": detail},
                original_url=f"https://example.test/{source_type}/{observation_id}",
                published_at=at,
            ),
        ),
        retrieved_at=at,
    )[0]
    return ClaimLedgerStore(database).ingest(
        observation,
        source_event_id=source_event_id,
        canonical_event_key=canonical_event_key,
        title=title,
        slot=slot,
        value=value,
        detail=detail,
        valid_at=at,
        evidence_text=detail or value,
    )


def _snapshot_observations(database) -> tuple[tuple[str, ...], tuple[str, ...]]:
    with database.connect() as connection:
        observations = tuple(
            row["id"] for row in connection.execute("SELECT id FROM observations ORDER BY id")
        )
        evidence = tuple(
            row["id"] for row in connection.execute("SELECT id FROM claim_evidence ORDER BY id")
        )
    return observations, evidence


def test_identity_is_versioned_replayable_and_explainable() -> None:
    first = fingerprint_claim(
        value="increased",
        detail="Limit increased to 1,000 requests per minute.",
        slot="limit",
    )
    second = fingerprint_claim(
        value="increased",
        detail="Limit was raised to one thousand requests/min.",
        slot="limit",
    )
    decision = compare_knowledge_identity(
        "increased",
        "Limit increased to 1,000 requests per minute.",
        "increased",
        "Limit was raised to one thousand requests/min.",
        left_slot="limit",
        right_slot="limit",
    )
    again = compare_knowledge_identity(
        "increased",
        "Limit increased to 1,000 requests per minute.",
        "increased",
        "Limit was raised to one thousand requests/min.",
        left_slot="limit",
        right_slot="limit",
    )
    assert first.identity_id == second.identity_id
    assert first.version == KNOWLEDGE_IDENTITY_VERSION
    assert decision == again
    assert decision.label == "same_target"
    assert decision.reason
    assert decision.confidence == "high"
    assert decision.version == KNOWLEDGE_IDENTITY_VERSION
    assert decision.shared_identity_id == first.identity_id


def test_gold_identity_pairs_cover_restatements_and_hard_negatives() -> None:
    assert _GOLD["version"] == KNOWLEDGE_IDENTITY_VERSION
    seen = {pair["id"] for pair in _GOLD["pairs"]}
    assert {
        "paraphrase-limit",
        "cross-source-latency",
        "added-detail",
        "numeric-change",
        "version-change",
        "negation-correction",
        "date-change",
        "stable-id-hard-negative",
        "lexical-overlap-widget-spark",
        "inconclusive-conflict",
    } <= seen
    for pair in _GOLD["pairs"]:
        decision = compare_knowledge_identity(
            pair["left"]["value"],
            pair["left"]["detail"],
            pair["right"]["value"],
            pair["right"]["detail"],
            left_slot=pair["left"]["slot"],
            right_slot=pair["right"]["slot"],
        )
        expected = pair["expected"]
        if expected == "not_same_target":
            assert decision.label != "same_target", pair["id"]
            assert decision.shared_identity_id is None
        else:
            assert decision.label == expected, f"{pair['id']}: {decision}"
        assert decision.reason
        assert decision.version == KNOWLEDGE_IDENTITY_VERSION
        if decision.label != "same_target":
            assert identity_may_hide(decision) is False


def test_cross_source_restatement_shares_one_knowledge_target(database) -> None:
    left = _ingest_claim(
        database,
        source_type="statuspage",
        source_key="abcd1234",
        observation_id="obs_latency_status",
        source_event_id="inc_latency_status",
        title="API latency",
        slot="status",
        value="investigating",
        detail="Investigating elevated latency.",
        at="2026-08-22T00:00:00Z",
    )
    right = _ingest_claim(
        database,
        source_type="rss_atom",
        source_key="https://status.example/feed.xml",
        observation_id="obs_latency_rss",
        source_event_id="inc_latency_rss",
        title="API latency feed",
        slot="status",
        value="investigating",
        detail="We are investigating elevated latency.",
        at="2026-08-22T00:01:00Z",
    )
    assert left.claim_id != right.claim_id
    with database.connect() as connection:
        before = ledger_world_state(connection)
        mappings = rebuild_knowledge_identities(
            connection, claim_ids=(left.claim_id, right.claim_id), created_at=10
        )
        replayed = rebuild_knowledge_identities(
            connection, claim_ids=(left.claim_id, right.claim_id), created_at=10
        )
        assert_feedback_does_not_mutate_ledger(before, ledger_world_state(connection))
    assert {item.claim_id for item in mappings} == {left.claim_id, right.claim_id}
    assert mappings[0].knowledge_id == mappings[1].knowledge_id
    assert {item.decision for item in mappings} == {"equivalent"}
    assert replayed == mappings


def test_different_facts_with_lexical_overlap_do_not_share_identity(database) -> None:
    widget = _ingest_claim(
        database,
        source_type="rss_atom",
        source_key="https://docs.example/feed.xml",
        observation_id="obs_widget",
        source_event_id="evt_widget",
        title="Widget retirement",
        slot="lifecycle",
        value="retired",
        detail="Widget retired on 2026-07-30",
        at="2026-08-22T00:00:00Z",
    )
    spark = _ingest_claim(
        database,
        source_type="json_feed",
        source_key="https://eng.example/feed.json",
        observation_id="obs_spark",
        source_event_id="evt_spark",
        title="Spark retirement",
        slot="lifecycle",
        value="retired",
        detail="Spark retired on 2026-07-30",
        at="2026-08-22T00:00:00Z",
    )
    decision = compare_knowledge_identity(
        "retired",
        "Widget retired on 2026-07-30",
        "retired",
        "Spark retired on 2026-07-30",
        left_slot="lifecycle",
        right_slot="lifecycle",
    )
    assert decision.label != "same_target"
    with database.connect() as connection:
        mappings = rebuild_knowledge_identities(
            connection, claim_ids=(widget.claim_id, spark.claim_id)
        )
    by_claim = {item.claim_id: item.knowledge_id for item in mappings}
    assert by_claim[widget.claim_id] != by_claim[spark.claim_id]


def test_evidence_attaches_to_identity_without_rewriting_claim_ids(database) -> None:
    left = _ingest_claim(
        database,
        source_type="statuspage",
        source_key="abcd1234",
        observation_id="obs_ev_left",
        source_event_id="inc_ev_left",
        title="API latency",
        slot="status",
        value="investigating",
        detail="Investigating elevated latency.",
        at="2026-08-22T00:00:00Z",
    )
    right = _ingest_claim(
        database,
        source_type="rss_atom",
        source_key="https://status.example/feed.xml",
        observation_id="obs_ev_right",
        source_event_id="inc_ev_right",
        title="API latency feed",
        slot="status",
        value="investigating",
        detail="We are investigating elevated latency.",
        at="2026-08-22T00:01:00Z",
    )
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('learner', 0)")
        mappings = rebuild_knowledge_identities(
            connection, claim_ids=(left.claim_id, right.claim_id)
        )
        knowledge_id = mappings[0].knowledge_id
        appended = append_knowledge_evidence(
            connection,
            user_id="learner",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_left_knew",
            claim_id=left.claim_id,
            event_id=left.event_id,
            created_at=5,
        )
        assert appended is True
        left_row = list_knowledge_evidence(
            connection, user_id="learner", claim_id=left.claim_id
        )[0]
        assert left_row.claim_id == left.claim_id
        grouped = list_knowledge_evidence_for_identity(
            connection, user_id="learner", knowledge_id=knowledge_id
        )
        assert [row.claim_id for row in grouped] == [left.claim_id]
        via_target = list_knowledge_evidence(
            connection, user_id="learner", knowledge_id=knowledge_id
        )
        assert via_target == grouped
        derived = replay_knowledge_state_for_identity(
            connection, user_id="learner", knowledge_id=knowledge_id
        )
        assert derived.state == STATE_KNOWN
        right_only = replay_knowledge_state(
            connection, user_id="learner", claim_id=right.claim_id
        )
        assert right_only.state == STATE_UNKNOWN
        stored = connection.execute(
            "SELECT id, value_text FROM state_claims WHERE id IN (?, ?) ORDER BY id",
            (left.claim_id, right.claim_id),
        ).fetchall()
        assert {row["id"] for row in stored} == {left.claim_id, right.claim_id}


def test_get_feed_still_does_not_mark_known_for_shared_identity(database) -> None:
    left = _ingest_claim(
        database,
        source_type="statuspage",
        source_key="abcd1234",
        observation_id="obs_feed_left",
        source_event_id="inc_feed_left",
        title="API latency",
        slot="status",
        value="investigating",
        detail="Investigating elevated latency.",
        at="2026-08-22T00:00:00Z",
    )
    right = _ingest_claim(
        database,
        source_type="rss_atom",
        source_key="https://status.example/feed.xml",
        observation_id="obs_feed_right",
        source_event_id="inc_feed_right",
        title="API latency feed",
        slot="status",
        value="investigating",
        detail="We are investigating elevated latency.",
        at="2026-08-22T00:01:00Z",
    )
    LedgerProjector(database).project_event(left.event_id)
    LedgerProjector(database).project_event(right.event_id)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('learner', 0)")
        rebuild_knowledge_identities(connection, claim_ids=(left.claim_id, right.claim_id))
    FeedProjector(database).project_event_for_user(user_id="learner", event_id=left.event_id)
    FeedProjector(database).project_event_for_user(user_id="learner", event_id=right.event_id)

    items, _ = FeedStore(database).list_feed(
        "learner", relation=None, item_status=None, cursor=None, limit=50
    )
    assert len(items) >= 2
    with database.connect() as connection:
        states = {
            row["claim_id"]: row["state"]
            for row in connection.execute(
                """
                SELECT claim_id, state FROM user_claim_exposures
                WHERE user_id = 'learner' AND claim_id IN (?, ?)
                """,
                (left.claim_id, right.claim_id),
            )
        }
        assert set(states) == {left.claim_id, right.claim_id}
        assert set(states.values()) == {"delivered"}
        mapping = resolve_claim_knowledge_id(connection, left.claim_id)
        assert mapping is not None
        derived = replay_knowledge_state_for_identity(
            connection, user_id="learner", knowledge_id=mapping.knowledge_id
        )
        assert derived.state == STATE_UNKNOWN
        assert derived.visibility == "show"
        assert may_hide(state=derived.state, confidence=derived.confidence) is False
        kinds = {
            row.kind
            for row in list_knowledge_evidence_for_identity(
                connection, user_id="learner", knowledge_id=mapping.knowledge_id
            )
        }
        assert kinds == {KIND_DELIVERED}


def test_uncertain_identity_never_causes_hide(database) -> None:
    left = _ingest_claim(
        database,
        source_type="statuspage",
        source_key="abcd1234",
        observation_id="obs_unc_left",
        source_event_id="inc_unc_left",
        title="Database issue",
        slot="status",
        value="issue",
        detail="database latency issue",
        at="2026-08-22T00:00:00Z",
    )
    right = _ingest_claim(
        database,
        source_type="statuspage",
        source_key="efgh5678",
        observation_id="obs_unc_right",
        source_event_id="inc_unc_right",
        title="Database issue",
        slot="status",
        value="issue",
        detail="database capacity issue",
        at="2026-08-22T00:01:00Z",
    )
    decision = compare_knowledge_identity(
        "issue",
        "database latency issue",
        "issue",
        "database capacity issue",
        left_slot="status",
        right_slot="status",
    )
    assert decision.label == "uncertain"
    assert identity_may_hide(decision) is False
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('learner', 0)")
        mappings = rebuild_knowledge_identities(
            connection, claim_ids=(left.claim_id, right.claim_id)
        )
        by_id = {item.claim_id: item.knowledge_id for item in mappings}
        assert by_id[left.claim_id] != by_id[right.claim_id]
        append_knowledge_evidence(
            connection,
            user_id="learner",
            kind=KIND_ALREADY_KNEW,
            source_id="fb_unc_left",
            claim_id=left.claim_id,
            event_id=left.event_id,
            created_at=3,
        )
        left_state = replay_knowledge_state(
            connection, user_id="learner", claim_id=left.claim_id
        )
        right_identity = replay_knowledge_state_for_identity(
            connection, user_id="learner", knowledge_id=by_id[right.claim_id]
        )
        assert left_state.state == STATE_KNOWN
        assert left_state.visibility == "hide"
        assert visibility_for_identity(decision, left_state) == "show"
        assert right_identity.state == STATE_UNKNOWN
        assert right_identity.visibility == "show"
        assert may_hide(state=right_identity.state, confidence=right_identity.confidence) is False


def test_event_identity_repair_rebuilds_maps_without_deleting_observations(database) -> None:
    first = _ingest_claim(
        database,
        source_type="statuspage",
        source_key="abcd1234",
        observation_id="obs_repair_a",
        source_event_id="inc_repair_a",
        title="Shared incident",
        slot="status",
        value="investigating",
        detail="Investigating elevated latency.",
        at="2026-08-22T00:00:00Z",
        canonical_event_key="latency-repair",
    )
    second = _ingest_claim(
        database,
        source_type="rss_atom",
        source_key="https://status.example/feed.xml",
        observation_id="obs_repair_b",
        source_event_id="inc_repair_b",
        title="Other incident",
        slot="status",
        value="investigating",
        detail="We are investigating elevated latency.",
        at="2026-08-22T00:01:00Z",
    )
    observations_before, evidence_before = _snapshot_observations(database)
    with database.connect() as connection:
        observation_payloads = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT id, payload_json FROM observations ORDER BY id"
            )
        )
        ensure_claim_knowledge_mapping(
            connection,
            claim_id=first.claim_id,
            value="investigating",
            detail="Investigating elevated latency.",
            slot="status",
        )
        ensure_claim_knowledge_mapping(
            connection,
            claim_id=second.claim_id,
            value="investigating",
            detail="We are investigating elevated latency.",
            slot="status",
        )

    EventIdentityRepairService(database).merge_events(
        source_event_id=second.event_id,
        target_event_id=first.event_id,
        reason="same incident restated across sources",
        created_at="2026-08-22T00:02:00Z",
    )

    observations_after, evidence_after = _snapshot_observations(database)
    assert observations_after == observations_before
    assert evidence_after == evidence_before
    with database.connect() as connection:
        after_claims = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT id, payload_json FROM observations ORDER BY id"
            )
        )
        assert after_claims == observation_payloads
        left = resolve_claim_knowledge_id(connection, first.claim_id)
        right = resolve_claim_knowledge_id(connection, second.claim_id)
        assert left is not None and right is not None
        assert left.knowledge_id == right.knowledge_id
        assert connection.execute(
            "SELECT 1 FROM state_claims WHERE id = ?", (first.claim_id,)
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM state_claims WHERE id = ?", (second.claim_id,)
        ).fetchone()
