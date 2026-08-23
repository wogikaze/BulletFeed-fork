from pathlib import Path

from app.database import Database
from app.services.source_ingestion import NormalizedObservation, SourceIngestionPipeline


def test_source_ingestion_is_idempotent_across_source_kinds(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    pipeline = SourceIngestionPipeline(database)
    items = (
        NormalizedObservation(
            source_type="github_release",
            source_key="openai/openai-python",
            source_observation_id="release:123",
            payload={"tag_name": "v1.0.0"},
            original_url="https://github.com/openai/openai-python/releases/tag/v1.0.0",
            published_at="2026-08-20T00:00:00Z",
        ),
        NormalizedObservation(
            source_type="osv",
            source_key="PyPI:requests",
            source_observation_id="GHSA-test",
            payload={"id": "GHSA-test"},
            original_url="https://osv.dev/vulnerability/GHSA-test",
            published_at="2026-08-20T00:00:00Z",
        ),
    )

    first = pipeline.ingest_many(items, retrieved_at="2026-08-22T00:00:00Z")
    second = pipeline.ingest_many(items, retrieved_at="2026-08-22T00:05:00Z")

    assert [item.id for item in first] == [item.id for item in second]
    assert {item.source_type for item in first} == {"github_release", "osv"}
