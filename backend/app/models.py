from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    github_auth_configured: bool


class AuthorizationStart(BaseModel):
    flow_id: str
    authorization_url: HttpUrl
    poll_token: str
    expires_in_seconds: int


class AuthorizationStatus(BaseModel):
    status: Literal["pending", "connected", "failed", "expired"]
    github_login: str | None = None
    app_access_token: str | None = None
    refresh_token: str | None = None
    detail: str | None = None


class GitHubProfile(BaseModel):
    id: int
    login: str
    avatar_url: HttpUrl | None = None


class GitHubRepository(BaseModel):
    id: int
    full_name: str
    private: bool
    html_url: HttpUrl
    description: str | None = None
    language: str | None = None
    updated_at: str


class ReleaseItem(BaseModel):
    id: int
    tag_name: str
    name: str | None = None
    html_url: HttpUrl
    published_at: str | None = None
    prerelease: bool
    summary: str = Field(max_length=500)


class OsvQuery(BaseModel):
    ecosystem: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9.+_-]+$")
    package: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)


class VulnerabilityItem(BaseModel):
    id: str
    modified: str | None = None


class FeedItem(BaseModel):
    title: str = Field(max_length=300)
    link: HttpUrl
    published: str | None = None
    summary: str = Field(max_length=500)


class FeedPreview(BaseModel):
    title: str = Field(max_length=300)
    source_url: HttpUrl
    items: list[FeedItem]


class StatuspageSummary(BaseModel):
    page_name: str
    status: str
    indicator: str
    unresolved_incidents: int
    scheduled_maintenances: int
