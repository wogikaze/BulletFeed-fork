"""Record a restore-identity snapshot of the release SQLite database."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def database_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_revisions(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT revision_id FROM schema_migrations ORDER BY revision_id"
        ).fetchall()
    finally:
        connection.close()
    return [str(row[0]) for row in rows]


def record_snapshot(*, database_path: Path, snapshot_dir: Path) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot_db = snapshot_dir / f"bulletfeed-{created_at}.db"
    source = sqlite3.connect(database_path)
    destination = sqlite3.connect(snapshot_db)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()

    identity = {
        "snapshot_id": created_at,
        "source_database_path": database_path.as_posix(),
        "snapshot_database_path": snapshot_db.as_posix(),
        "source_sha256": database_sha256(database_path),
        "snapshot_sha256": database_sha256(snapshot_db),
        "schema_revisions": schema_revisions(snapshot_db),
        "created_at": created_at,
    }
    identity_path = snapshot_dir / f"bulletfeed-{created_at}.identity.json"
    identity_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return identity_path


def main() -> None:
    database_path = Path(os.getenv("BULLETFEED_DATABASE_PATH", "data/bulletfeed.db"))
    snapshot_dir = Path(os.getenv("BULLETFEED_SNAPSHOT_DIR", "/snapshots"))
    identity_path = record_snapshot(database_path=database_path, snapshot_dir=snapshot_dir)
    print(identity_path)


if __name__ == "__main__":
    main()
