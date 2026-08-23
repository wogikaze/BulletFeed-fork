from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict

from app.config import get_settings
from app.database import Database
from app.db.release_lifecycle import install_release_lifecycle_guards, record_worker_heartbeat
from app.sync_worker import WatchSyncWorker


async def run_release_worker() -> None:
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    install_release_lifecycle_guards(database)

    idle_sleep_seconds = float(os.getenv("BULLETFEED_WORKER_IDLE_SECONDS", "5"))
    poll_seconds = int(os.getenv("BULLETFEED_WORKER_POLL_SECONDS", "300"))
    batch_size = int(os.getenv("BULLETFEED_WORKER_BATCH_SIZE", "20"))
    if idle_sleep_seconds <= 0:
        raise ValueError("BULLETFEED_WORKER_IDLE_SECONDS must be positive")

    worker = WatchSyncWorker(
        settings,
        database,
        poll_interval_seconds=poll_seconds,
        batch_size=batch_size,
    )
    while True:
        record_worker_heartbeat(database, detail="running")
        summary = await worker.run_once()
        record_worker_heartbeat(database, detail=json.dumps(asdict(summary), sort_keys=True))
        if summary.attempted:
            print(json.dumps(asdict(summary), sort_keys=True), flush=True)
        await asyncio.sleep(idle_sleep_seconds)


def main() -> None:
    asyncio.run(run_release_worker())


if __name__ == "__main__":
    main()
