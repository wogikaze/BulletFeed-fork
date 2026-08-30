from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def backup_sqlite(source_path: Path, backup_dir: Path, *, retention_days: int = 14) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC)
    destination_path = backup_dir / f"bulletfeed-{now.strftime('%Y%m%dT%H%M%SZ')}.db"
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(destination_path)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()

    cutoff = now - timedelta(days=retention_days)
    for candidate in backup_dir.glob("bulletfeed-*.db"):
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
        if modified < cutoff:
            candidate.unlink(missing_ok=True)
    return destination_path


def main() -> None:
    source_path = Path(os.getenv("BULLETFEED_DATABASE_PATH", "data/bulletfeed.db"))
    backup_dir = Path(os.getenv("BULLETFEED_BACKUP_DIR", "/backups"))
    retention_days = int(os.getenv("BULLETFEED_BACKUP_RETENTION_DAYS", "14"))
    destination_path = backup_sqlite(source_path, backup_dir, retention_days=retention_days)
    print(destination_path)


if __name__ == "__main__":
    main()
