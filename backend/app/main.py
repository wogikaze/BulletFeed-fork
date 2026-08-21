from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Database
from app.models import HealthResponse
from app.routers import auth, sources


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

settings = get_settings()
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Auth-Poll-Token"],
    )

app.include_router(auth.router)
app.include_router(sources.router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(github_auth_configured=settings.github_auth_configured)
