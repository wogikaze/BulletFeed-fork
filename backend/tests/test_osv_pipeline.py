from pathlib import Path

from app.database import Database
from app.services.osv_pipeline import ingest_osv_events


def _vulnerability(summary: str, modified: str) -> dict:
    return {
        "id": "GHSA-test-1234",
        "published": "2026-08-20T10:00:00Z",
        "modified": modified,
        "summary": summary,
        "details": summary,
        "aliases": ["CVE-2026-0001"],
    }


def test_osv_revisions_reach_public_event_projection(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    first = ingest_osv_events(
        database,
        ecosystem="PyPI",
        package="requests",
        version="2.0.0",
        vulnerabilities=[_vulnerability("Initial advisory.", "2026-08-20T10:01:00Z")],
        retrieved_at="2026-08-20T10:02:00Z",
    )
    second = ingest_osv_events(
        database,
        ecosystem="PyPI",
        package="requests",
        version="2.0.0",
        vulnerabilities=[
            _vulnerability(
                "Advisory now includes mitigation guidance.",
                "2026-08-20T11:00:00Z",
            )
        ],
        retrieved_at="2026-08-20T11:01:00Z",
    )

    assert first.event_ids == second.event_ids
    event_id = first.event_ids[0]
    with database.connect() as connection:
        event = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        deltas = connection.execute(
            "SELECT * FROM deltas WHERE event_id = ? ORDER BY occurred_at, id",
            (event_id,),
        ).fetchall()
        sources = connection.execute(
            "SELECT * FROM event_sources WHERE event_id = ? ORDER BY retrieved_at, id",
            (event_id,),
        ).fetchall()

    assert event["current_phase"] == "affected"
    assert event["current_summary"] == "Advisory now includes mitigation guidance."
    assert [row["type"] for row in deltas] == ["new_fact", "detail"]
    assert {row["publisher"] for row in sources} == {"OSV"}
    assert {row["kind"] for row in sources} == {"osv"}
