import html
import secrets
import time
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from app.config import Settings, get_settings
from app.database import Database
from app.dependencies import get_cipher, get_database, require_session
from app.models import AuthorizationStart, AuthorizationStatus, GitHubProfile, GitHubRepository
from app.security import TokenCipher, create_pkce_pair
from app.services import github

router = APIRouter(prefix="/v1", tags=["authentication"])


def _require_github_config(settings: Settings) -> None:
    if not settings.github_auth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub authentication is not configured; copy .env.example to .env",
        )


@router.post("/auth/github/start", response_model=AuthorizationStart)
def start_github_authorization(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
) -> AuthorizationStart:
    _require_github_config(settings)
    flow_id = secrets.token_urlsafe(24)
    state_value = secrets.token_urlsafe(32)
    poll_token = secrets.token_urlsafe(32)
    verifier, challenge = create_pkce_pair()
    expires_in = 600
    database.create_oauth_flow(
        flow_id=flow_id,
        state=state_value,
        poll_token=poll_token,
        encrypted_verifier=cipher.encrypt(verifier),
        expires_at=int(time.time()) + expires_in,
    )
    query = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.github_callback_url,
            "state": state_value,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return AuthorizationStart(
        flow_id=flow_id,
        authorization_url=f"https://github.com/login/oauth/authorize?{query}",
        poll_token=poll_token,
        expires_in_seconds=expires_in,
    )


@router.get("/auth/github/callback", response_class=HTMLResponse)
async def github_callback(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
    code: Annotated[str, Query(min_length=1, max_length=300)],
    state_value: Annotated[str, Query(alias="state", min_length=20, max_length=300)],
) -> HTMLResponse:
    _require_github_config(settings)
    flow = database.claim_oauth_flow(state_value)
    if flow is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state is invalid or expired"
        )
    try:
        verifier = cipher.decrypt(flow["pkce_verifier_encrypted"])
        token_data = await github.exchange_code(settings, code, verifier)
        github_token = token_data["access_token"]
        github_user = await github.get_user(settings, github_token)
        now = int(time.time())
        token_expires_at = now + int(token_data["expires_in"]) if token_data.get("expires_in") else None
        session_lifetime = min(int(token_data.get("expires_in", 28_800)), 28_800)
        app_access_token = secrets.token_urlsafe(48)
        database.complete_oauth_flow(
            flow_id=flow["flow_id"],
            github_user=github_user,
            encrypted_github_token=cipher.encrypt(github_token),
            github_token_expires_at=token_expires_at,
            app_access_token=app_access_token,
            encrypted_app_access_token=cipher.encrypt(app_access_token),
            session_expires_at=now + session_lifetime,
        )
    except Exception as exc:
        database.fail_oauth_flow(flow["flow_id"], "GitHub authorization failed")
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub authorization failed"
        ) from exc

    login = html.escape(str(github_user["login"]))
    return HTMLResponse(
        "<!doctype html><html lang='ja'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>BulletFeed</title><body style='font-family:sans-serif;padding:32px'>"
        f"<h1>GitHub連携が完了しました</h1><p>{login} として連携しました。</p>"
        "<p>BulletFeedアプリに戻ってください。この画面にトークンは含まれていません。</p>"
        "</body></html>"
    )


@router.get("/auth/github/status/{flow_id}", response_model=AuthorizationStatus)
def github_authorization_status(
    flow_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
    poll_token: Annotated[str | None, Header(alias="X-Auth-Poll-Token")] = None,
) -> AuthorizationStatus:
    _require_github_config(settings)
    if not poll_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Poll token is required")
    result = database.get_oauth_status(flow_id, poll_token, cipher)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Authorization flow was not found")
    return AuthorizationStatus(**result)


@router.get("/me/github", response_model=GitHubProfile)
def github_profile(session: Annotated[dict, Depends(require_session)]) -> GitHubProfile:
    return GitHubProfile(
        id=session["github_user_id"],
        login=session["login"],
        avatar_url=session["avatar_url"],
    )


@router.get("/me/github/repositories", response_model=list[GitHubRepository])
async def github_repositories(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[dict, Depends(require_session)],
) -> list[GitHubRepository]:
    repositories = await github.list_repositories(settings, session["github_token"])
    return [
        GitHubRepository(
            id=item["id"],
            full_name=item["full_name"],
            private=item["private"],
            html_url=item["html_url"],
            description=item.get("description"),
            language=item.get("language"),
            updated_at=item["updated_at"],
        )
        for item in repositories
        if all(key in item for key in ("id", "full_name", "private", "html_url", "updated_at"))
    ]
