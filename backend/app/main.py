import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Database
from app.db.release_lifecycle import install_release_lifecycle_guards, worker_is_fresh
from app.db.source_health import summarize_source_health
from app.db.topic_catalog import install_topic_catalog
from app.dependencies import get_database
from app.errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from app.models import HealthResponse
from app.observability import public_counters
from app.release_identity import release_identity
from app.routers import (
    auth,
    events,
    feed,
    integrations,
    knowledge_bootstrap,
    me,
    session_telemetry,
    sessions,
    source_discovery,
    source_subscriptions,
    webhooks,
)
from app.services.github_webhook_delivery import summarize_webhook_health
from app.services.web_snapshots import SnapshotStore


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    install_topic_catalog(database)
    install_release_lifecycle_guards(database)
    worker_thread: threading.Thread | None = None
    worker_stop = threading.Event()
    if settings.embed_source_sync_worker:
        from app.release_worker import run_release_worker

        def _run_embedded_worker() -> None:
            # Own event loop: RSS DNS/parse/ingest is sync and must not stall API requests.
            asyncio.run(run_release_worker(stop_event=worker_stop))

        worker_thread = threading.Thread(
            target=_run_embedded_worker,
            name="bulletfeed-source-sync",
            daemon=True,
        )
        worker_thread.start()
    try:
        yield
    finally:
        if worker_thread is not None:
            worker_stop.set()
            worker_thread.join(timeout=5)


app = FastAPI(
    title="BulletFeed Backend",
    version="0.1.0",
    description="BulletFeed API and source synchronization backend.",
    lifespan=lifespan,
)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

settings = get_settings()
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Auth-Poll-Token"],
    )

app.include_router(sessions.router)
app.include_router(feed.router)
app.include_router(events.router)
app.include_router(me.router)
app.include_router(knowledge_bootstrap.router)
app.include_router(session_telemetry.router)
app.include_router(source_subscriptions.router)
app.include_router(source_discovery.router)
app.include_router(integrations.router)
app.include_router(auth.router)
app.include_router(webhooks.router)
if os.environ.get("BULLETFEED_ACCEPTANCE_HARNESS") == "1":
    from app.routers import acceptance_harness

    app.include_router(acceptance_harness.router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(github_auth_configured=settings.github_auth_configured)


@app.get("/health/identity", tags=["system"])
def health_identity() -> dict[str, object]:
    return {"status": "ok", "release": release_identity()}


def _snapshot_storage(database: Database) -> dict[str, int]:
    root = Path(database.path).resolve().parent / "web_snapshots"
    if not root.is_dir():
        return {
            "snapshot_count": 0,
            "body_bytes": 0,
            "metadata_bytes": 0,
            "total_bytes": 0,
            "temporary_directory_count": 0,
        }
    return SnapshotStore(root).storage_stats().as_dict()


@app.get("/health/ready", tags=["system"])
def readiness(
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    try:
        with database.connect() as connection:
            connection.execute("SELECT 1").fetchone()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready",
        ) from exc
    if not worker_is_fresh(database):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Source sync worker heartbeat is stale or missing",
        )
    ingestion = summarize_source_health(database, now=int(time.time()))
    return {
        "status": "ready",
        "database": "ok",
        "sourceSyncWorker": "ok",
        "sourceIngestion": ingestion.as_public_dict(),
        "snapshotStorage": _snapshot_storage(database),
        "webhook": summarize_webhook_health(database).as_public_dict(),
        "release": release_identity(),
        "pipeline": public_counters(),
    }


@app.get("/health/sources", tags=["system"])
def source_health(
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    summary = summarize_source_health(database, now=int(time.time()))
    return {
        "workerHeartbeat": summary.worker_heartbeat,
        "sourceIngestion": summary.as_public_dict(),
        "snapshotStorage": _snapshot_storage(database),
        "webhook": summarize_webhook_health(database).as_public_dict(),
        "pipeline": public_counters(),
    }
