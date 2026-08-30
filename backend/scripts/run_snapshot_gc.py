"""Run retention/capacity GC for unreferenced Web snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.database import Database
from app.services.web_snapshots import (
    SnapshotStore,
    referenced_snapshot_ids,
)


def main() -> int:
    database_path = Path(os.getenv("BULLETFEED_DATABASE_PATH", "data/bulletfeed.db"))
    snapshot_root = Path(
        os.getenv(
            "BULLETFEED_SNAPSHOT_DIR",
            database_path.resolve().parent / "web_snapshots",
        )
    )
    retention_days = int(os.getenv("BULLETFEED_SNAPSHOT_RETENTION_DAYS", "30"))
    max_bytes_raw = os.getenv("BULLETFEED_SNAPSHOT_MAX_BYTES", "").strip()
    max_bytes = int(max_bytes_raw) if max_bytes_raw else None
    database = Database(database_path)
    database.initialize()
    store = SnapshotStore(snapshot_root)
    before = store.storage_stats()
    result = store.garbage_collect(
        referenced_ids=referenced_snapshot_ids(database),
        retention_days=retention_days,
        max_bytes=max_bytes,
    )
    after = store.storage_stats()
    print(
        json.dumps(
            {
                "gc_version": "m5-snapshot-gc-v1",
                "storage_before": before.as_dict(),
                "gc": result.as_dict(),
                "storage_after": after.as_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
