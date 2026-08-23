from pathlib import Path

import pytest

from app.database import Database
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline
from app.stores.claim_ledger_store import ClaimLedgerStore


def test_hacker_news_discovery_cannot_create_or_support_claims(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    observations = SourceIngestionPipeline(database).ingest_many(
        (
            NormalizedObservation(
                source_type="hacker_news_discovery",
                source_key="topstories",
                source_observation_id="123",
                payload={
                    "id": 123,
                    "title": "Acme releases Widget 2.0",
                    "url": "https://acme.example/releases/widget-2",
                },
                original_url="https://acme.example/releases/widget-2",
                published_at="2026-08-20T10:00:00Z",
            ),
            NormalizedObservation(
                source_type="github_release",
                source_key="acme/widget",
                source_observation_id="release:42",
                payload={"id": 42, "tag_name": "v2.0.0"},
                original_url="https://github.com/acme/widget/releases/tag/v2.0.0",
                published_at="2026-08-20T10:00:00Z",
            ),
        ),
        retrieved_at="2026-08-20T10:01:00Z",
    )
    hn, release = observations
    ledger = ClaimLedgerStore(database)

    with pytest.raises(ValueError, match="not eligible for claim evidence"):
        ledger.ingest(
            hn,
            source_event_id="123",
            title="HN candidate",
            slot="publication_state",
            value="published",
            detail="candidate",
            valid_at="2026-08-20T10:00:00Z",
            evidence_text="HN candidate",
        )

    claim = ledger.ingest(
        release,
        source_event_id="release:42",
        title="Widget 2.0",
        slot="release_state",
        value="released",
        detail="Widget 2.0 released",
        valid_at="2026-08-20T10:00:00Z",
        evidence_text="Widget 2.0 released",
    )
    with pytest.raises(ValueError, match="not eligible for claim evidence"):
        ledger.add_evidence(claim.claim_id, hn, evidence_text="HN repeats the release")

    with database.connect() as connection:
        evidence_types = connection.execute(
            """
            SELECT DISTINCT o.source_type
            FROM claim_evidence e
            JOIN observations o ON o.id = e.observation_id
            WHERE e.claim_id = ?
            """,
            (claim.claim_id,),
        ).fetchall()
    assert [row["source_type"] for row in evidence_types] == ["github_release"]
