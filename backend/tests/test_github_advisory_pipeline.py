from pathlib import Path

from app.database import Database
from app.services.github_advisory_pipeline import ingest_github_advisory_events


def _advisory(withdrawn_at: str | None, updated_at: str) -> dict:
    return {
        "ghsa_id": "GHSA-test-1234",
        "html_url": "https://github.com/advisories/GHSA-test-1234",
        "summary": "Example vulnerability",
        "severity": "high",
        "published_at": "2026-08-20T10:00:00Z",
        "updated_at": updated_at,
        "withdrawn_at": withdrawn_at,
    }


def test_github_advisory_identity_is_independent_of_ecosystem_scope(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    global_result = ingest_github_advisory_events(
        database,
        advisories=[_advisory(None, "2026-08-20T10:01:00Z")],
        retrieved_at="2026-08-20T10:02:00Z",
        ecosystem=None,
    )
    pip_result = ingest_github_advisory_events(
        database,
        advisories=[_advisory(None, "2026-08-20T10:01:00Z")],
        retrieved_at="2026-08-20T10:03:00Z",
        ecosystem="pip",
    )

    assert global_result.event_ids == pip_result.event_ids
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0] == 1


def test_github_advisory_withdrawal_becomes_state_update(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    first = ingest_github_advisory_events(
        database,
        advisories=[_advisory(None, "2026-08-20T10:01:00Z")],
        retrieved_at="2026-08-20T10:02:00Z",
        ecosystem="pip",
    )
    second = ingest_github_advisory_events(
        database,
        advisories=[_advisory("2026-08-21T09:00:00Z", "2026-08-21T09:01:00Z")],
        retrieved_at="2026-08-21T09:02:00Z",
        ecosystem="pip",
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

    assert event["current_phase"] == "withdrawn"
    assert [row["type"] for row in deltas] == ["new_fact", "state_update"]
    assert {row["publisher"] for row in sources} == {"GitHub"}
    assert {row["kind"] for row in sources} == {"github_advisory"}
