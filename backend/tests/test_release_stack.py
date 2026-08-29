from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from app.database import Database
from app.db.migrations import KNOWN_REVISIONS

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from record_db_snapshot import database_sha256, record_snapshot  # noqa: E402
from start_release_stack import start_release_stack  # noqa: E402
from validate_release_config import validate_release_env  # noqa: E402


def _valid_env(path: Path, *, database_path: str) -> None:
    path.write_text(
        "\n".join(
            [
                "BULLETFEED_GITHUB_CLIENT_ID=release-client",
                "BULLETFEED_GITHUB_CLIENT_SECRET=release-secret",
                f"BULLETFEED_TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}",
                f"BULLETFEED_DATABASE_PATH={database_path}",
                "BULLETFEED_REQUEST_TIMEOUT_SECONDS=10",
                "BULLETFEED_MAX_RESPONSE_BYTES=1048576",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_example_env_fails_closed_before_start() -> None:
    errors = validate_release_env(BACKEND / ".env.release.example")
    assert any("GITHUB_CLIENT_ID" in item for item in errors)
    assert any("TOKEN_ENCRYPTION_KEY" in item for item in errors)


def test_invalid_fernet_key_fails_closed(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.release"
    env_path.write_text(
        "\n".join(
            [
                "BULLETFEED_GITHUB_CLIENT_ID=release-client",
                "BULLETFEED_GITHUB_CLIENT_SECRET=release-secret",
                "BULLETFEED_TOKEN_ENCRYPTION_KEY=not-a-fernet-key",
                "BULLETFEED_DATABASE_PATH=/data/bulletfeed.db",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    errors = validate_release_env(env_path)
    assert any("Fernet" in item for item in errors)


def test_developer_default_database_path_fails_closed(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.release"
    _valid_env(env_path, database_path="data/bulletfeed.db")
    errors = validate_release_env(env_path)
    assert any("DATABASE_PATH" in item for item in errors)


def test_one_command_validate_only_accepts_release_env(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.release"
    _valid_env(env_path, database_path="/data/bulletfeed.db")
    assert (
        start_release_stack(
            env_file=env_path,
            compose_file=BACKEND / "compose.release.yml",
            validate_only=True,
        )
        == 0
    )


def test_compose_declares_persistent_data_and_snapshot_volumes() -> None:
    compose = (BACKEND / "compose.release.yml").read_text(encoding="utf-8")
    assert "bulletfeed-data:/data" in compose
    assert "bulletfeed-snapshots:/snapshots" in compose
    assert "scripts/record_db_snapshot.py" in compose
    assert "BULLETFEED_DATABASE_PATH: /data/bulletfeed.db" in compose


def test_fresh_and_upgrade_initialize_to_same_revision_head(tmp_path: Path) -> None:
    fresh = Database(tmp_path / "fresh.db")
    fresh.initialize()

    prior = Database(tmp_path / "prior.db")
    prior.initialize()
    with prior.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE revision_id IN ('17', '18')")
    prior.initialize()

    with fresh.connect() as fresh_conn, prior.connect() as prior_conn:
        fresh_revisions = {
            row[0] for row in fresh_conn.execute("SELECT revision_id FROM schema_migrations")
        }
        prior_revisions = {
            row[0] for row in prior_conn.execute("SELECT revision_id FROM schema_migrations")
        }
        assert fresh_revisions == set(KNOWN_REVISIONS)
        assert prior_revisions == set(KNOWN_REVISIONS)


def test_persistent_data_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "data" / "bulletfeed.db"
    first = Database(path)
    first.initialize()
    with first.connect() as connection:
        connection.execute(
            "INSERT INTO users (id, created_at) VALUES (?, ?)",
            ("user-release-persist", 1),
        )

    restarted = Database(path)
    restarted.initialize()
    with restarted.connect() as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE id = ?",
            ("user-release-persist",),
        ).fetchone()
        assert row is not None
        revisions = {
            item[0] for item in connection.execute("SELECT revision_id FROM schema_migrations")
        }
        assert revisions == set(KNOWN_REVISIONS)


def test_snapshot_identity_matches_restore_copy(tmp_path: Path) -> None:
    database_path = tmp_path / "live.db"
    database = Database(database_path)
    database.initialize()
    identity_path = record_snapshot(
        database_path=database_path,
        snapshot_dir=tmp_path / "snapshots",
    )
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    snapshot_db = Path(identity["snapshot_database_path"])
    assert set(identity["schema_revisions"]) == set(KNOWN_REVISIONS)
    assert identity["snapshot_sha256"] == database_sha256(snapshot_db)

    restored = tmp_path / "restored.db"
    source = sqlite3.connect(snapshot_db)
    destination = sqlite3.connect(restored)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()
    assert database_sha256(restored) == identity["snapshot_sha256"]
