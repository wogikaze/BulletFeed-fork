from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Database
from app.errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from app.models import HealthResponse
from app.routers import auth, events, feed, integrations, me, sessions


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    Database(settings.database_path).initialize()
    yield


app = FastAPI(
    title="BulletFeed Local Backend",
    version="0.1.0",
    description="Local prototype. GitHub credentials are kept on this server, never in the Android app.",
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
app.include_router(integrations.router)
app.include_router(auth.router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(github_auth_configured=settings.github_auth_configured)
