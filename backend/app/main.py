import os
import time
from contextlib import asynccontextmanager
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
from app.routers import (
    auth,
    events,
    feed,
    integrations,
    knowledge_bootstrap,
    me,
    sessions,
    source_discovery,
    source_subscriptions,
    webhooks,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    install_topic_catalog(database)
    install_release_lifecycle_guards(database)
    yield


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
    }


@app.get("/health/sources", tags=["system"])
def source_health(
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    summary = summarize_source_health(database, now=int(time.time()))
    return {
        "workerHeartbeat": summary.worker_heartbeat,
        "sourceIngestion": summary.as_public_dict(),
        "pipeline": public_counters(),
    }
