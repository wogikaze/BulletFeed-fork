from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.config import Settings
from app.database import Database
from app.dependencies import get_cipher, get_database, get_settings, require_user
from app.routers.auth import start_github_authorization_for_user
from app.schemas.integrations import (
    GithubAuthorizeResponse,
    GithubConnection,
    GithubImportResult,
    GithubRepoImportRequest,
    GithubRepositoryPage,
    GithubRepositoryUpdate,
    GithubRepositoryUpdateResult,
    NotificationItem,
    NotificationList,
    NotificationReadAllResponse,
    NotificationReadPatch,
    SecurityAlert,
    SecurityAlertList,
    SecurityAlertPatch,
)
from app.security import TokenCipher
from app.services.feed_projection import FeedProjector
from app.services.repository_topic_inference import sync_selected_repository_topics
from app.stores.integration_store import IntegrationStore
from app.stores.me_store import MeStore

router = APIRouter(prefix="/v1", tags=["integrations"])


def _store(
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
) -> IntegrationStore:
    return IntegrationStore(database, cipher)


@router.get("/me/integrations/github", response_model=GithubConnection)
def get_github_connection(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
) -> GithubConnection:
    return store.github_connection(user["user_id"])


@router.post("/me/integrations/github/authorize", response_model=GithubAuthorizeResponse)
def authorize_github(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
    user: Annotated[dict, Depends(require_user)],
) -> GithubAuthorizeResponse:
    started = start_github_authorization_for_user(
        settings,
        database,
        cipher,
        user_id=user["user_id"],
    )
    return GithubAuthorizeResponse(
        authorization_url=str(started.authorization_url),
        flow_id=started.flow_id,
        poll_token=started.poll_token,
        expires_in_seconds=started.expires_in_seconds,
    )


@router.get("/me/integrations/github/repositories", response_model=GithubRepositoryPage)
async def list_github_repositories(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> GithubRepositoryPage:
    return await store.list_repositories(user["user_id"], q, cursor, limit, settings)


@router.put("/me/integrations/github/repositories", response_model=GithubRepositoryUpdateResult)
async def update_github_repositories(
    body: GithubRepositoryUpdate,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
) -> GithubRepositoryUpdateResult:
    connection = await store.update_repositories(user["user_id"], body.repository_ids, settings)
    synced = await sync_selected_repository_topics(
        database,
        cipher,
        user_id=user["user_id"],
        settings=settings,
    )
    with database.connect() as db_connection:
        state_row = db_connection.execute(
            "SELECT onboarding_state FROM users WHERE id = ?",
            (user["user_id"],),
        ).fetchone()
    if state_row is not None and state_row["onboarding_state"] == "repository_pending":
        MeStore(database).mark_repository_setup_ready(user["user_id"])
    else:
        FeedProjector(database).reproject_user(user_id=user["user_id"])
    return GithubRepositoryUpdateResult(
        connected=connection.connected,
        credential_state=connection.credential_state,
        account_login=connection.account_login,
        added_topics=synced.added,
        already_tracked_topics=synced.already_tracked,
        inspected_repository_count=synced.inspected_repository_count,
        failed_repository_count=synced.failed_repository_count,
    )


@router.post("/me/integrations/github/import", response_model=GithubImportResult)
async def import_github_repository_keywords(
    body: GithubRepoImportRequest,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GithubImportResult:
    return await store.import_repository_keywords(user["user_id"], body.full_name, settings)


@router.delete("/me/integrations/github", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_github(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
) -> Response:
    store.disconnect_github(user["user_id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/security/alerts", response_model=SecurityAlertList)
def list_security_alerts(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
    alert_status: Annotated[str | None, Query(alias="status")] = None,
    repository_id: str | None = None,
) -> SecurityAlertList:
    return SecurityAlertList(items=store.list_alerts(user["user_id"], alert_status, repository_id))


@router.get("/me/security/alerts/{alert_id}", response_model=SecurityAlert)
def get_security_alert(
    alert_id: str,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
) -> SecurityAlert:
    return store.get_alert(user["user_id"], alert_id)


@router.patch("/me/security/alerts/{alert_id}", response_model=SecurityAlert)
def patch_security_alert(
    alert_id: str,
    body: SecurityAlertPatch,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
) -> SecurityAlert:
    return store.patch_alert(user["user_id"], alert_id, body.status)


@router.get("/me/notifications", response_model=NotificationList)
def list_notifications(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
    item_status: Annotated[Literal["unread", "all"] | None, Query(alias="status")] = None,
) -> NotificationList:
    return NotificationList(
        items=store.list_notifications(user["user_id"], only_unread=item_status == "unread")
    )


@router.patch("/me/notifications/{notification_id}", response_model=NotificationItem)
def patch_notification(
    notification_id: str,
    body: NotificationReadPatch,
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
) -> NotificationItem:
    del body
    return store.mark_notification_read(user["user_id"], notification_id)


@router.post("/me/notifications/read-all", response_model=NotificationReadAllResponse)
def read_all_notifications(
    user: Annotated[dict, Depends(require_user)],
    store: Annotated[IntegrationStore, Depends(_store)],
) -> NotificationReadAllResponse:
    return NotificationReadAllResponse(updated_count=store.mark_all_notifications_read(user["user_id"]))
