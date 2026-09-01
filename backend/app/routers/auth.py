import secrets
import time
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.database import Database
from app.dependencies import get_cipher, get_database, require_user
from app.models import AuthorizationStart, AuthorizationStatus
from app.schemas.integrations import GithubAuthorizeResponse
from app.security import TokenCipher, create_pkce_pair
from app.services import github
from app.services.oauth_flow_policy import create_user_oauth_flow

router = APIRouter(prefix="/v1", tags=["authentication"])

_USER_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
_REFRESH_TTL_SECONDS = 365 * 24 * 60 * 60
_ANDROID_OAUTH_RETURN_URI = "bulletfeed://oauth/github"


def _require_github_config(settings: Settings) -> None:
    if not settings.github_auth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub authentication is not configured; copy .env.example to .env",
        )


def _start_github_authorization(
    settings: Settings,
    database: Database,
    cipher: TokenCipher,
    *,
    user_id: str | None,
) -> AuthorizationStart:
    _require_github_config(settings)
    flow_id = secrets.token_urlsafe(24)
    state_value = secrets.token_urlsafe(32)
    poll_token = secrets.token_urlsafe(32)
    verifier, challenge = create_pkce_pair()
    expires_in = 600
    create_user_oauth_flow(
        database,
        flow_id=flow_id,
        user_id=user_id,
        state=state_value,
        poll_token=poll_token,
        encrypted_verifier=cipher.encrypt(verifier),
        expires_at=int(time.time()) + expires_in,
        purpose="account_recovery" if user_id is None else "user_link",
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


def start_github_authorization_for_user(
    settings: Settings,
    database: Database,
    cipher: TokenCipher,
    *,
    user_id: str,
) -> AuthorizationStart:
    return _start_github_authorization(
        settings,
        database,
        cipher,
        user_id=user_id,
    )


@router.post("/auth/github/start", response_model=AuthorizationStart)
def start_github_authorization(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
    user: Annotated[dict, Depends(require_user)],
) -> AuthorizationStart:
    return start_github_authorization_for_user(
        settings,
        database,
        cipher,
        user_id=user["user_id"],
    )


@router.post("/sessions/recover/github", response_model=GithubAuthorizeResponse)
def start_github_account_recovery(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
) -> GithubAuthorizeResponse:
    started = _start_github_authorization(
        settings,
        database,
        cipher,
        user_id=None,
    )
    return GithubAuthorizeResponse(
        authorization_url=str(started.authorization_url),
        flow_id=started.flow_id,
        poll_token=started.poll_token,
        expires_in_seconds=started.expires_in_seconds,
    )


@router.get("/auth/github/callback", response_class=RedirectResponse)
async def github_callback(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    cipher: Annotated[TokenCipher, Depends(get_cipher)],
    code: Annotated[str, Query(min_length=1, max_length=300)],
    state_value: Annotated[str, Query(alias="state", min_length=20, max_length=300)],
) -> RedirectResponse:
    _require_github_config(settings)
    flow = database.claim_oauth_flow(state_value)
    if flow is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state is invalid or expired",
        )
    if flow["user_id"] is None and flow["detail"] != "account_recovery":
        database.fail_oauth_flow(flow["flow_id"], "Unbound OAuth flow is not an account recovery flow")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth flow is not valid for account recovery",
        )
    try:
        verifier = cipher.decrypt(flow["pkce_verifier_encrypted"])
        token_data = await github.exchange_code(settings, code, verifier)
        github_token = token_data["access_token"]
        github_user = await github.get_user(settings, github_token)
        now = int(time.time())
        token_expires_at = now + int(token_data["expires_in"]) if token_data.get("expires_in") else None
        app_access_token = secrets.token_urlsafe(48)
        refresh_token = secrets.token_urlsafe(64)
        database.complete_oauth_flow(
            flow_id=flow["flow_id"],
            user_id=flow["user_id"],
            github_user=github_user,
            encrypted_github_token=cipher.encrypt(github_token),
            github_token_expires_at=token_expires_at,
            app_access_token=app_access_token,
            encrypted_app_access_token=cipher.encrypt(app_access_token),
            refresh_token=refresh_token,
            encrypted_refresh_token=cipher.encrypt(refresh_token),
            user_session_expires_at=now + _USER_SESSION_TTL_SECONDS,
            refresh_expires_at=now + _REFRESH_TTL_SECONDS,
        )
    except ValueError as exc:
        database.fail_oauth_flow(flow["flow_id"], str(exc))
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        database.fail_oauth_flow(flow["flow_id"], "GitHub authorization failed")
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub authorization failed",
        ) from exc

    return RedirectResponse(
        url=_ANDROID_OAUTH_RETURN_URI,
        status_code=status.HTTP_303_SEE_OTHER,
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
