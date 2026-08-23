from pathlib import Path

from app.database import Database
from app.services.ledger_projection import LedgerProjector
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def test_claim_can_project_github_sbom_and_osv_evidence_separately(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    observations = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="osv",
                source_key="acme/widget",
                source_observation_id="GHSA-test|pkg:pypi/requests@2.0.0",
                payload={"id": "GHSA-test"},
                original_url="https://osv.dev/vulnerability/GHSA-test",
                published_at="2026-08-20T10:00:00Z",
            ),
            NormalizedObservation(
                source_type="github_sbom",
                source_key="acme/widget",
                source_observation_id="sbom",
                payload={"sbom": {"packages": []}},
                original_url="https://github.com/acme/widget",
                published_at=None,
            ),
        ),
        retrieved_at="2026-08-20T10:01:00Z",
    )

    ledger = ClaimLedgerStore(database)
    claim = ledger.ingest(
        observations[0],
        source_event_id="GHSA-test|pkg:pypi/requests@2.0.0",
        title="acme/widget — requests 2.0.0 — GHSA-test",
        slot="dependency_vulnerability",
        value="affected",
        detail="requests 2.0.0 is affected by GHSA-test.",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="GHSA-test affects requests 2.0.0.",
    )
    ledger.add_evidence(
        claim.claim_id,
        observations[1],
        evidence_text="The repository SBOM contains requests 2.0.0.",
    )

    LedgerProjector(database).project_event(claim.event_id)

    with database.connect() as connection:
        sources = connection.execute(
            "SELECT * FROM event_sources WHERE event_id = ? ORDER BY kind",
            (claim.event_id,),
        ).fetchall()
        mappings = connection.execute(
            "SELECT COUNT(*) FROM event_source_claim_map WHERE claim_id = ?",
            (claim.claim_id,),
        ).fetchone()[0]

    assert {row["kind"] for row in sources} == {"github_sbom", "osv"}
    assert {row["publisher"] for row in sources} == {"GitHub", "OSV"}
    assert mappings == 2
