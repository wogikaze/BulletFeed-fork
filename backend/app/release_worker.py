from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict
from threading import Event

from app.config import get_settings
from app.database import Database
from app.db.release_lifecycle import install_release_lifecycle_guards, record_worker_heartbeat
from app.sync_worker import WatchSyncWorker


async def _idle(stop_event: Event | None, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            return
        await asyncio.sleep(min(0.25, max(deadline - time.monotonic(), 0.0)))


async def run_release_worker(stop_event: Event | None = None) -> None:
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
    while stop_event is None or not stop_event.is_set():
        record_worker_heartbeat(database, detail="running")
        summary = await worker.run_once()
        record_worker_heartbeat(database, detail=json.dumps(asdict(summary), sort_keys=True))
        if summary.attempted:
            print(json.dumps(asdict(summary), sort_keys=True), flush=True)
        await _idle(stop_event, idle_sleep_seconds)


def main() -> None:
    asyncio.run(run_release_worker())


if __name__ == "__main__":
    main()
