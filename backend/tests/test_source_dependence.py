from app.services.source_dependence import evidence_dependence_key
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def _persist(database, item: NormalizedObservation):
    return SourceIngestionPipeline(database).ingest_many(
        [item],
        retrieved_at="2026-08-22T00:05:00Z",
    )[0]


def test_osv_and_github_advisory_share_upstream_dependence_key(database) -> None:
    osv = _persist(
        database,
        NormalizedObservation(
            source_type="osv",
            source_key="PyPI:example@1.0.0",
            source_observation_id="OSV-2026-1",
            payload={"id": "OSV-2026-1", "aliases": ["CVE-2026-1", "GHSA-abcd-1234-5678"]},
            original_url="https://osv.dev/vulnerability/OSV-2026-1",
            published_at="2026-08-22T00:00:00Z",
        ),
    )
    advisory = _persist(
        database,
        NormalizedObservation(
            source_type="github_advisory",
            source_key="pip",
            source_observation_id="GHSA-abcd-1234-5678",
            payload={"ghsa_id": "GHSA-abcd-1234-5678"},
            original_url="https://github.com/advisories/GHSA-abcd-1234-5678",
            published_at="2026-08-22T00:00:00Z",
        ),
    )

    canonical_key = "advisory:GHSA-ABCD-1234-5678"
    assert evidence_dependence_key(osv) == canonical_key
    assert evidence_dependence_key(advisory) == canonical_key


def test_source_count_does_not_equal_independent_evidence_count(database) -> None:
    ingestion = SourceIngestionPipeline(database)
    osv, advisory, sbom = ingestion.ingest_many(
        [
            NormalizedObservation(
                source_type="osv",
                source_key="acme/app",
                source_observation_id="OSV-2026-1|pkg:pypi/example@1.0.0",
                payload={
                    "vulnerability": {
                        "id": "OSV-2026-1",
                        "aliases": ["GHSA-abcd-1234-5678"],
                    }
                },
                original_url="https://osv.dev/vulnerability/OSV-2026-1",
                published_at="2026-08-22T00:00:00Z",
            ),
            NormalizedObservation(
                source_type="github_advisory",
                source_key="pip",
                source_observation_id="GHSA-abcd-1234-5678",
                payload={"ghsa_id": "GHSA-abcd-1234-5678"},
                original_url="https://github.com/advisories/GHSA-abcd-1234-5678",
                published_at="2026-08-22T00:00:00Z",
            ),
            NormalizedObservation(
                source_type="github_sbom",
                source_key="acme/app",
                source_observation_id="sbom",
                payload={"sbom": {"packages": []}},
                original_url="https://github.com/acme/app/dependency-graph/sbom",
                published_at=None,
            ),
        ],
        retrieved_at="2026-08-22T00:05:00Z",
    )

    ledger = ClaimLedgerStore(database)
    claim = ledger.ingest(
        osv,
        source_event_id="OSV-2026-1|pkg:pypi/example@1.0.0",
        title="example 1.0.0 vulnerability",
        slot="dependency_vulnerability",
        value="affected",
        detail="example 1.0.0 is affected",
        valid_at="2026-08-22T00:00:00Z",
        evidence_text="OSV reports the vulnerability",
    )
    ledger.add_evidence(
        claim.claim_id,
        advisory,
        evidence_text="GitHub Advisory republishes the same GHSA family",
    )
    ledger.add_evidence(
        claim.claim_id,
        sbom,
        evidence_text="Repository SBOM independently establishes package presence",
    )

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT dependence_key FROM claim_evidence WHERE claim_id = ? ORDER BY dependence_key, id",
            (claim.claim_id,),
        ).fetchall()
    assert len(rows) == 3
    assert [row["dependence_key"] for row in rows].count("advisory:GHSA-ABCD-1234-5678") == 2
    assert ledger.independent_evidence_count(claim.claim_id) == 2
