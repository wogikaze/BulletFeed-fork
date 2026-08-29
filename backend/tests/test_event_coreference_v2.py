from pathlib import Path

from app.database import Database
from app.evaluation.coreference import (
    compare_delta_adversarial_case,
    evaluate_coreference_identity,
    lexical_delta_coreference_decision,
)
from app.evaluation.delta_adversarial_gold import load_delta_adversarial_gold
from app.services.event_coreference import (
    COREFERENCE_VERSION,
    CoreferenceInput,
    EventCandidate,
    EventCoreferenceEngine,
    compare_event_mentions,
)
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore

_V01 = Path(__file__).parent / "gold" / "delta_adversarial" / "v01"


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "coreference-v2.db")
    database.initialize()
    return database


def _observation(
    database: Database,
    *,
    source_type: str,
    source_key: str,
    observation_id: str,
    title: str,
    at: str,
):
    return SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type=source_type,
                source_key=source_key,
                source_observation_id=observation_id,
                payload={"title": title},
                original_url=f"https://example.com/{observation_id}",
                published_at=at,
            ),
        ),
        retrieved_at=at,
    )[0]


def _candidate(
    *,
    event_id: str = "evt-prior",
    source_type: str = "rss_atom",
    source_key: str = "vendor-feed",
    source_event_id: str = "prior",
    title: str,
    value: str,
    detail: str,
    valid_at: str = "2026-08-20T10:00:00Z",
) -> EventCandidate:
    return EventCandidate(
        event_id=event_id,
        source_type=source_type,
        source_key=source_key,
        source_event_id=source_event_id,
        title=title,
        created_at=valid_at,
        latest_value=value,
        latest_detail=detail,
        latest_valid_at=valid_at,
        score=0.0,
    )


def _incoming(
    *,
    source_type: str = "json_feed",
    source_key: str = "vendor-json",
    source_event_id: str = "incoming",
    title: str,
    subject: str,
    valid_at: str = "2026-08-20T11:00:00Z",
) -> CoreferenceInput:
    return CoreferenceInput(source_type, source_key, source_event_id, title, subject, valid_at)


def _assert_decision_contract(decision) -> None:
    assert decision.reason
    assert decision.confidence in {"high", "medium", "low"}
    assert decision.version
    assert COREFERENCE_VERSION in decision.version


def test_shared_advisory_id_merges_cross_source_paraphrase() -> None:
    decision = compare_event_mentions(
        _incoming(
            title="Widget overflow advisory published",
            subject="Security advisory CVE-2024-12345 affects Widget in production builds.",
        ),
        _candidate(
            source_type="osv",
            source_key="GHSA-aaaa-bbbb-cccc",
            title="OSV record for Widget",
            value="affected",
            detail="CVE-2024-12345 is present in Widget 4.x package builds.",
        ),
    )

    _assert_decision_contract(decision)
    assert decision.label == "same_event"
    assert decision.confidence == "high"
    assert "advisory" in decision.reason


def test_conflicting_stable_ids_are_a_hard_negative() -> None:
    decision = compare_event_mentions(
        _incoming(
            title="log4j advisory",
            subject="CVE-2021-44228 affects log4j-core 2.14.1.",
        ),
        _candidate(
            title="log4j advisory",
            value="critical",
            detail="CVE-2021-45046 affects log4j-core 2.14.1.",
        ),
    )

    _assert_decision_contract(decision)
    assert decision.label == "different_event"
    assert decision.confidence == "high"
    assert "stable_id" in decision.hard_guards


def test_entity_alias_paraphrase_is_same_event() -> None:
    entra = compare_event_mentions(
        _incoming(
            title="Entra sign-in incident",
            subject="Microsoft Entra ID sign-in is degraded.",
        ),
        _candidate(
            title="Azure AD sign-in incident",
            value="degraded",
            detail="Azure Active Directory sign-in is degraded.",
        ),
    )
    twitter = compare_event_mentions(
        _incoming(
            title="X API quota notice",
            subject="X API v2 rate limit remains 300 requests per 15 minutes.",
        ),
        _candidate(
            title="Twitter API quota notice",
            value="limit 300/15m",
            detail="Twitter API v2 rate limit remains 300 requests per 15 minutes.",
        ),
    )

    _assert_decision_contract(entra)
    _assert_decision_contract(twitter)
    assert entra.label == "same_event"
    assert twitter.label == "same_event"


def test_number_word_restatement_merges_without_title_overlap() -> None:
    decision = compare_event_mentions(
        _incoming(
            title="Request cap restated",
            subject="The per-minute request cap is now one thousand.",
        ),
        _candidate(
            title="API limit increased",
            value="active",
            detail="Limit increased to 1,000 requests per minute.",
        ),
    )

    _assert_decision_contract(decision)
    assert decision.label == "same_event"
    assert "semantic equivalence" in decision.reason


def test_adjacent_product_names_prefer_false_split() -> None:
    decision = compare_event_mentions(
        _incoming(
            title="React Native 19 is generally available",
            subject="React Native 19 is generally available.",
        ),
        _candidate(
            title="React 19 is generally available",
            value="released",
            detail="React 19 is generally available.",
        ),
    )

    _assert_decision_contract(decision)
    assert decision.label != "same_event"
    assert decision.label in {"different_event", "uncertain"}


def test_hard_guards_block_equivalence_based_merge_for_numeric_date_and_negation() -> None:
    numeric = compare_event_mentions(
        _incoming(
            title="Upload limit notice",
            subject="Upload limit increased to 1000 GB.",
        ),
        _candidate(
            title="Upload quota notice",
            value="limit 1000 mb",
            detail="Upload limit increased to 1000 MB.",
        ),
    )
    dated = compare_event_mentions(
        _incoming(
            title="Support window",
            subject="Support retires August 30, 2026.",
        ),
        _candidate(
            title="Retirement window",
            value="retires",
            detail="Support retires July 30, 2026.",
        ),
    )
    negation = compare_event_mentions(
        _incoming(
            title="Runtime policy",
            subject="Python 3.10 is not supported",
        ),
        _candidate(
            title="Runtime status",
            value="supported",
            detail="Python 3.10 is supported",
        ),
    )

    for decision in (numeric, dated, negation):
        _assert_decision_contract(decision)
        assert decision.label != "same_event"
        assert decision.hard_guards
    assert "numeric" in numeric.hard_guards
    assert "date" in dated.hard_guards
    assert "negation" in negation.hard_guards


def test_ambiguous_nearby_incidents_do_not_merge() -> None:
    decision = compare_event_mentions(
        _incoming(
            title="Actions runners degraded",
            subject="GitHub Actions runners are degraded in eu-west-1.",
        ),
        _candidate(
            title="Actions runners degraded",
            value="degraded",
            detail="GitHub Actions runners are degraded in us-east-1.",
        ),
    )

    _assert_decision_contract(decision)
    assert decision.label != "same_event"
    if decision.label == "uncertain":
        assert decision.confidence == "low"


def test_structured_identity_still_outranks_semantic_evidence(tmp_path: Path) -> None:
    database = _database(tmp_path)
    observation = _observation(
        database,
        source_type="statuspage",
        source_key="github",
        observation_id="incident-a:update-1",
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
            "Completely different wording about a queue stall",
            "Newly queued jobs never leave the queued state.",
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

    _assert_decision_contract(same)
    _assert_decision_contract(different)
    assert same.label == "same_event"
    assert same.confidence == "high"
    assert same.candidate_event_id == claim.event_id
    assert different.label == "different_event"
    assert different.candidate_event_id is None


def test_cross_source_advisory_paraphrase_is_retrieved_and_aliased(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = ClaimLedgerStore(database)
    first_observation = _observation(
        database,
        source_type="osv",
        source_key="osv-widget",
        observation_id="cve-12345",
        title="OSV Widget overflow",
        at="2026-08-20T10:00:00Z",
    )
    first = store.ingest(
        first_observation,
        source_event_id="cve-12345",
        title="OSV Widget overflow",
        slot="advisory",
        value="affected",
        detail="CVE-2024-12345 is present in Widget 4.x package builds.",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="CVE-2024-12345",
    )
    second_observation = _observation(
        database,
        source_type="rss_atom",
        source_key="security-blog",
        observation_id="widget-overflow-writeup",
        title="Widget overflow writeup",
        at="2026-08-20T12:00:00Z",
    )
    second = store.ingest(
        second_observation,
        source_event_id="widget-overflow-writeup",
        title="Widget overflow writeup",
        slot="advisory",
        value="affected",
        detail="Security advisory CVE-2024-12345 affects Widget in production builds.",
        valid_at="2026-08-20T12:00:00Z",
        evidence_text="CVE-2024-12345",
        coreference_subject="Security advisory CVE-2024-12345 affects Widget in production builds.",
    )

    assert second.event_id == first.event_id
    engine = EventCoreferenceEngine(database, candidate_limit=20)
    incoming = CoreferenceInput(
        "rss_atom",
        "security-blog",
        "fresh-writeup",
        "Another Widget overflow note",
        "Researchers published CVE-2024-12345 against Widget.",
        "2026-08-20T13:00:00Z",
    )
    candidates = engine.retrieve_candidates(incoming)
    assert candidates.size <= 20
    assert first.event_id in {candidate.event_id for candidate in candidates.candidates}


def test_delta_adversarial_gold_reports_false_merge_and_false_split_separately() -> None:
    corpus = load_delta_adversarial_gold(_V01)
    lexical_decisions = {case.case_id: lexical_delta_coreference_decision(case) for case in corpus.cases}
    decisions = {case.case_id: compare_delta_adversarial_case(case) for case in corpus.cases}

    lexical, _lexical_delta = evaluate_coreference_identity(corpus, lexical_decisions)
    report, delta = evaluate_coreference_identity(corpus, decisions)

    assert report.pair_count == len(corpus.cases)
    assert delta.false_merge_count == report.false_merge_count
    assert delta.false_split_count == report.false_split_count
    assert report.false_merge_count >= 0
    assert report.false_split_count >= 0
    assert report.false_merge_count <= lexical.false_merge_count
    assert report.false_merge_count == 0
    assert report.same_event_precision >= lexical.same_event_precision
    assert report.same_event_precision >= 0.80

    paraphrase_families = {
        "cross_source_restatement",
        "same_fact_different_wording",
        "entity_alias_product_rename",
    }
    paraphrase = [
        case
        for case in corpus.cases
        if case.family in paraphrase_families and case.same_gold_event
    ]
    paraphrase_hits = sum(1 for case in paraphrase if decisions[case.case_id].label == "same_event")
    lexical_hits = sum(1 for case in paraphrase if lexical_decisions[case.case_id].label == "same_event")
    assert paraphrase_hits >= lexical_hits

    for decision in decisions.values():
        _assert_decision_contract(decision)
        if decision.label == "uncertain":
            assert decision.confidence == "low"
