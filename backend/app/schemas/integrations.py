from typing import Literal

from app.schemas.common import ApiModel

GithubCredentialState = Literal["connected", "reauthorization_required", "disconnected"]


class GithubConnection(ApiModel):
    connected: bool
    credential_state: GithubCredentialState
    account_login: str | None = None


class GithubAuthorizeResponse(ApiModel):
    authorization_url: str
    flow_id: str
    poll_token: str
    expires_in_seconds: int


class GithubRepository(ApiModel):
    id: str
    full_name: str
    html_url: str
    private: bool
    description: str | None = None
    language: str | None = None
    selected: bool
    updated_at: str


class GithubRepositoryPage(ApiModel):
    items: list[GithubRepository]
    next_cursor: str | None = None


class GithubRepositoryUpdate(ApiModel):
    repository_ids: list[str]


class GithubRepositoryUpdateResult(ApiModel):
    connected: bool
    credential_state: GithubCredentialState
    account_login: str | None = None
    added_topics: list[str] = []
    already_tracked_topics: list[str] = []
    inspected_repository_count: int = 0
    failed_repository_count: int = 0


class GithubRepoImportRequest(ApiModel):
    full_name: str


class GithubImportedTopic(ApiModel):
    name: str
    type: str = "technology"


class GithubImportResult(ApiModel):
    full_name: str
    keywords: list[str]
    added_topics: list[str]


class SecurityAlertRepository(ApiModel):
    id: str
    full_name: str


class SecurityAlertPackage(ApiModel):
    name: str
    current_version: str
    fixed_version: str
    dependency_type: str


class SecurityAlert(ApiModel):
    id: str
    advisory_id: str
    cve: str | None
    title: str
    summary: str
    severity: Literal["critical", "high", "medium", "low"]
    status: Literal["open", "in_progress", "resolved", "not_affected"]
    repository: SecurityAlertRepository
    package: SecurityAlertPackage
    source: str
    detected_at: str
    evidence: str
    recommendation: str
    cvss_score: float | None = None


class SecurityAlertList(ApiModel):
    items: list[SecurityAlert]


class SecurityAlertPatch(ApiModel):
    status: Literal["open", "in_progress", "resolved", "not_affected"]


class NotificationTarget(ApiModel):
    type: str
    id: str


class NotificationItem(ApiModel):
    id: str
    title: str
    summary: str
    category: Literal["security", "breaking_change", "release"]
    priority: Literal["urgent", "high", "normal"]
    occurred_at: str
    read: bool
    target: NotificationTarget


class NotificationList(ApiModel):
    items: list[NotificationItem]


class NotificationReadPatch(ApiModel):
    read: bool = True


class NotificationReadAllResponse(ApiModel):
    updated_count: int
