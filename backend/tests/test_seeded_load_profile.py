from pathlib import Path

from app.database import Database
from app.evaluation.release_smoke import run_release_smoke
from app.evaluation.seeded_load_profile import PROFILE_VERSION, run_seeded_load_profile


def test_seeded_load_profile_records_stages_and_bottlenecks(tmp_path: Path) -> None:
    database = Database(tmp_path / "load.db")
    database.initialize()
    report = run_seeded_load_profile(
        database,
        incident_count=6,
        updates_per_incident=2,
        user_count=2,
    )
    assert report.version == PROFILE_VERSION
    assert report.projected_item_count >= 6
    names = {stage.name for stage in report.stages}
    assert {"statuspage_ingest", "feed_list", "feed_projection"} <= names
    assert len(report.bottlenecks) <= 3
    assert all(stage.elapsed_ms >= 0 for stage in report.stages)
    with database.connect() as connection:
        index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_feed_items_user_dismissed'"
        ).fetchone()
    assert index is not None


def test_release_smoke_covers_health_feed_and_reopen(tmp_path: Path) -> None:
    report = run_release_smoke(tmp_path / "smoke.db")
    assert report["health"] == 200
    assert report["ready"] == 200
    assert report["session"] == 200
    assert report["feed"] == 200
    assert report["usersAfterReopen"] >= 1
