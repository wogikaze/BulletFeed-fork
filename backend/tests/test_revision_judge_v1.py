from pathlib import Path

from app.database import Database
from app.services.semantic_delta import ClaimSnapshot, DeltaContext, judge_revision
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def claim(value: str, detail: str = "", valid_at: str = "2026-08-22T00:00:00Z") -> ClaimSnapshot:
    return ClaimSnapshot(value=value, detail=detail, valid_at=valid_at)


def test_semantic_paraphrase_is_non_novel():
    decision = judge_revision(
        claim("active", "Limit increased to 1,000 requests per minute."),
        claim("active", "Limit was raised to one thousand requests/min."),
    )

    assert decision.revision_type == "NON_NOVEL"
    assert decision.version == "revision-judge-v1"


def test_same_value_with_new_detail_is_detail():
    decision = judge_revision(
        claim("released", "Widget v3 is available"),
        claim("released", "Widget v3 is available with migration notes"),
    )

    assert decision.revision_type == "DETAIL"


def test_numeric_value_change_at_later_time_is_state_update():
    decision = judge_revision(
        claim("limit 1000 requests/min", valid_at="2026-08-22T00:00:00Z"),
        claim("limit 1200 requests/min", valid_at="2026-08-22T01:00:00Z"),
    )

    assert decision.revision_type == "STATE_UPDATE"
    assert decision.confidence == "high"


def test_explicit_correction_is_high_authority():
    decision = judge_revision(
        claim("supported"),
        claim("not supported", valid_at="2026-08-22T01:00:00Z"),
        context=DeltaContext(explicit_correction=True),
    )

    assert decision.revision_type == "CORRECTION"
    assert decision.confidence == "high"
    assert "explicitly" in decision.reason


def test_same_time_ambiguous_value_abstains_into_unresolved_conflict():
    decision = judge_revision(
        claim("database latency issue"),
        claim("database capacity issue"),
    )

    assert decision.revision_type == "UNRESOLVED_CONTRADICTION"
    assert decision.abstained is True
    assert decision.confidence == "low"


def test_ledger_persists_revision_reason_confidence_and_version(tmp_path: Path):
    database = Database(tmp_path / "semantic.db")
    observations = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="rss_atom",
                source_key="https://example.com/feed.xml",
                source_observation_id="a",
                payload={"title": "Limit update"},
                original_url="https://example.com/a",
                published_at="2026-08-22T00:00:00Z",
            ),
            NormalizedObservation(
                source_type="rss_atom",
                source_key="https://example.com/feed.xml",
                source_observation_id="b",
                payload={"title": "Limit restatement"},
                original_url="https://example.com/b",
                published_at="2026-08-22T01:00:00Z",
            ),
        ),
        retrieved_at="2026-08-22T02:00:00Z",
    )
    store = ClaimLedgerStore(database)
    store.ingest(
        observations[0],
        source_event_id="limit",
        canonical_event_key="example:limit",
        title="API limit",
        slot="limit_state",
        value="active",
        detail="Limit increased to 1,000 requests per minute.",
        valid_at="2026-08-22T00:00:00Z",
        evidence_text="Limit increased to 1,000 requests per minute.",
    )
    second = store.ingest(
        observations[1],
        source_event_id="limit-restatement",
        canonical_event_key="example:limit",
        title="API limit",
        slot="limit_state",
        value="active",
        detail="Limit was raised to one thousand requests/min.",
        valid_at="2026-08-22T01:00:00Z",
        evidence_text="Limit was raised to one thousand requests/min.",
    )

    assert second.relation_type == "NON_NOVEL"
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT decision_reason, decision_confidence, decision_version, decision_abstained
            FROM claim_relations WHERE new_claim_id = ?
            """,
            (second.claim_id,),
        ).fetchone()
    assert row["decision_reason"]
    assert row["decision_confidence"] in {"high", "medium"}
    assert row["decision_version"] == "revision-judge-v1"
    assert row["decision_abstained"] == 0
