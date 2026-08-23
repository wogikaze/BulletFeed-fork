from pathlib import Path

from app.database import Database
from app.services.event_coreference import CoreferenceInput, EventCoreferenceEngine
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def _observation(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    source_observation_id: str,
    title: str,
    at: str,
):
    return SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type=source_type,
                source_key=source_key,
                source_observation_id=source_observation_id,
                payload={"title": title},
                original_url=f"https://example.com/{source_observation_id}",
                published_at=at,
            ),
        ),
        retrieved_at=at,
    )[0]


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "coreference.db")
    database.initialize()
    return database


def test_structured_identity_is_strongest_and_distinct_ids_are_hard_negative(tmp_path: Path):
    database = _database(tmp_path)
    observation = _observation(
        database,
        source_type="statuspage",
        source_key="github",
        source_observation_id="incident-a:update-1",
        title="Incident with Actions",
        at="2026-08-20T10:00:00Z",
    )
    claim = ClaimLedgerStore(database).ingest(
        observation,
        source_event_id="incident-a",
        title="Incident with Actions",
        slot="status",
        value="investigating",
        detail="Actions is degraded",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="Actions is degraded",
    )
    engine = EventCoreferenceEngine(database)

    same = engine.resolve(
        CoreferenceInput(
            "statuspage",
            "github",
            "incident-a",
            "Incident with Actions",
            "Actions is degraded",
            "2026-08-20T10:05:00Z",
        )
    )
    different = engine.resolve(
        CoreferenceInput(
            "statuspage",
            "github",
            "incident-b",
            "Incident with Actions",
            "Actions is degraded",
            "2026-08-20T10:05:00Z",
        )
    )

    assert same.label == "same_event"
    assert same.confidence == "high"
    assert same.candidate_event_id == claim.event_id
    assert different.label == "different_event"
    assert different.candidate_event_id is None


def test_cross_source_policy_lifecycle_uses_common_coreference_interface(tmp_path: Path):
    database = _database(tmp_path)
    first_observation = _observation(
        database,
        source_type="rss_atom",
        source_key="github-changelog",
        source_observation_id="models-retirement-announcement",
        title="GitHub Models retirement",
        at="2026-07-01T09:00:00Z",
    )
    first = ClaimLedgerStore(database).ingest(
        first_observation,
        source_event_id="models-retirement-announcement",
        title="GitHub Models retirement",
        slot="lifecycle",
        value="retirement_announced",
        detail="GitHub Models retirement scheduled for July 30, 2026",
        valid_at="2026-07-01T09:00:00Z",
        evidence_text="Retirement scheduled",
    )
    engine = EventCoreferenceEngine(database)
    decision = engine.resolve(
        CoreferenceInput(
            "json_feed",
            "github-changelog-json",
            "models-retired",
            "GitHub Models retirement",
            "GitHub Models retirement completed July 30, 2026",
            "2026-07-30T09:00:00Z",
        )
    )

    assert decision.label == "same_event"
    assert decision.candidate_event_id == first.event_id
    assert decision.version.startswith("event-coreference-v1[")


def test_version_hard_negative_prevents_same_entity_release_merge(tmp_path: Path):
    database = _database(tmp_path)
    observation = _observation(
        database,
        source_type="rss_atom",
        source_key="vendor-feed",
        source_observation_id="widget-4.0.0",
        title="Widget v4.0.0 release",
        at="2026-08-20T10:00:00Z",
    )
    ClaimLedgerStore(database).ingest(
        observation,
        source_event_id="widget-4.0.0",
        title="Widget v4.0.0 release",
        slot="release",
        value="released",
        detail="Widget v4.0.0 is available",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="Widget v4.0.0 is available",
    )

    decision = EventCoreferenceEngine(database).resolve(
        CoreferenceInput(
            "json_feed",
            "vendor-json",
            "widget-4.0.1",
            "Widget v4.0.1 release",
            "Widget v4.0.1 is available",
            "2026-08-20T11:00:00Z",
        )
    )

    assert decision.label == "different_event"


def test_claim_ledger_can_opt_into_coreference_and_records_stable_alias(tmp_path: Path):
    database = _database(tmp_path)
    store = ClaimLedgerStore(database)
    first_observation = _observation(
        database,
        source_type="rss_atom",
        source_key="vendor-feed",
        source_observation_id="retirement-a",
        title="Service retirement",
        at="2026-08-01T10:00:00Z",
    )
    first = store.ingest(
        first_observation,
        source_event_id="retirement-a",
        title="Service retirement",
        slot="lifecycle",
        value="announced",
        detail="Service retirement is scheduled",
        valid_at="2026-08-01T10:00:00Z",
        evidence_text="scheduled",
    )
    second_observation = _observation(
        database,
        source_type="json_feed",
        source_key="vendor-json",
        source_observation_id="retirement-b",
        title="Service retirement",
        at="2026-08-02T10:00:00Z",
    )
    second = store.ingest(
        second_observation,
        source_event_id="retirement-b",
        title="Service retirement",
        slot="lifecycle",
        value="announced",
        detail="Service retirement is scheduled",
        valid_at="2026-08-02T10:00:00Z",
        evidence_text="scheduled",
        coreference_subject="Service retirement is scheduled",
    )

    assert second.event_id == first.event_id
    with database.connect() as connection:
        alias = connection.execute(
            "SELECT event_id, decision_version FROM event_identity_aliases WHERE event_id = ?",
            (first.event_id,),
        ).fetchone()
    assert alias is not None
    assert alias["decision_version"].startswith("event-coreference-v1[")


def test_candidate_retrieval_is_bounded_and_private_events_fail_closed(tmp_path: Path):
    database = _database(tmp_path)
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES ('owner', 1), ('other', 1)")
        connection.execute(
            """
            INSERT INTO github_repo_watches (
                user_id, repository_id, full_name, selected, private
            ) VALUES ('owner', 'repo-1', 'acme/private', 1, 1)
            """
        )
    observation = _observation(
        database,
        source_type="github_release",
        source_key="acme/private",
        source_observation_id="release-1",
        title="Private Widget v1.0.0",
        at="2026-08-20T10:00:00Z",
    )
    claim = ClaimLedgerStore(database).ingest(
        observation,
        source_event_id="release-1",
        title="Private Widget v1.0.0",
        slot="release",
        value="released",
        detail="Private Widget v1.0.0 released",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="released",
    )
    LedgerProjector(database).project_event(claim.event_id)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO event_visibility (event_id, restricted) VALUES (?, 1)",
            (claim.event_id,),
        )
        connection.execute(
            """
            INSERT INTO event_user_access (event_id, user_id, expires_at)
            VALUES (?, 'owner', 4102444800)
            """,
            (claim.event_id,),
        )

    engine = EventCoreferenceEngine(database, candidate_limit=1)
    incoming = CoreferenceInput(
        "github_release",
        "acme/private",
        "release-1",
        "Private Widget v1.0.0",
        "released",
        "2026-08-20T10:00:00Z",
    )
    owner = engine.retrieve_candidates(incoming, user_id="owner")
    other = engine.retrieve_candidates(incoming, user_id="other")
    anonymous = engine.retrieve_candidates(incoming)

    assert owner.size == 1
    assert owner.candidates[0].event_id == claim.event_id
    assert other.size == 0
    assert anonymous.size == 0

    engine.record_alias(incoming.alias_key, claim.event_id, reason="test", created_at="2026-08-20T10:00:00Z")
    assert engine.resolve_alias(incoming.alias_key, user_id="owner") == claim.event_id
    assert engine.resolve_alias(incoming.alias_key, user_id="other") is None
    assert engine.resolve_alias(incoming.alias_key) is None
