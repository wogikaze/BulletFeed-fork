from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path


def main() -> int:
    database_path = Path(os.getenv("BULLETFEED_DATABASE_PATH", "data/bulletfeed.db"))
    max_age = int(os.getenv("BULLETFEED_WORKER_HEALTH_MAX_AGE_SECONDS", "30"))
    try:
        connection = sqlite3.connect(database_path)
        row = connection.execute(
            "SELECT heartbeat_at FROM worker_heartbeats WHERE name = 'source_sync'"
        ).fetchone()
    except sqlite3.Error:
        return 1
    finally:
        if "connection" in locals():
            connection.close()
    if row is None:
        return 1
    return 0 if int(time.time()) - int(row[0]) <= max_age else 1


if __name__ == "__main__":
    sys.exit(main())
