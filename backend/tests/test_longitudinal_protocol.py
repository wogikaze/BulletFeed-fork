import json
from pathlib import Path

from app.evaluation.longitudinal_qualification import (
    PROTOCOL_VERSION,
    Observation,
    classify_pair,
)

PROTOCOL = (
    Path(__file__).resolve().parent
    / "gold"
    / "source_qualification"
    / "v01"
    / "longitudinal_protocol.json"
)


def test_protocol_sample_is_stratified_and_hash_only() -> None:
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert payload["protocol_version"] == PROTOCOL_VERSION
    assert payload["parent_issue"] == 283
    assert payload["minimum_observations_per_source"] == 2
    assert payload["sample_count"] == len(payload["sample"])
    assert payload["sample_count"] >= 10
    families = payload["source_family_counts"]
    assert set(families) == {row["source_family"] for row in payload["sample"]}
    for row in payload["sample"]:
        assert row["fetch_url"].startswith("https://")
        assert row["t0_content_hash"]
        assert "body" not in row
        assert "raw_html" not in row


def test_missing_t1_is_unavailable_not_an_update_event() -> None:
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    row = payload["sample"][0]
    first = Observation(
        source_id=row["source_id"],
        source_family=row["source_family"],
        fetch_url=row["fetch_url"],
        acquired_at="2026-08-31T00:00:00Z",
        status_code=row["t0_status_code"],
        final_url=row["t0_final_url"],
        content_type=row["t0_content_type"],
        content_hash=row["t0_content_hash"],
        etag=None,
        last_modified=None,
    )
    assert classify_pair(first, None) == "unavailable"
    same = Observation(
        source_id=row["source_id"],
        source_family=row["source_family"],
        fetch_url=row["fetch_url"],
        acquired_at="2026-08-31T01:00:00Z",
        status_code=row["t0_status_code"],
        final_url=row["t0_final_url"],
        content_type=row["t0_content_type"],
        content_hash=row["t0_content_hash"],
        etag=None,
        last_modified=None,
    )
    assert classify_pair(first, same) == "unchanged"
