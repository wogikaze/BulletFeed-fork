import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet

from app.database import Database
from app.security import TokenCipher


def test_oauth_flow_and_session_lifecycle(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    cipher = TokenCipher(Fernet.generate_key().decode())
    state = secrets.token_urlsafe(32)
    poll_token = secrets.token_urlsafe(32)
    database.create_oauth_flow(
        flow_id="flow-1",
        user_id=None,
        state=state,
        poll_token=poll_token,
        encrypted_verifier=cipher.encrypt("verifier"),
        expires_at=int(time.time()) + 600,
    )

    flow = database.claim_oauth_flow(state)
    assert flow is not None
    assert cipher.decrypt(flow["pkce_verifier_encrypted"]) == "verifier"

    app_token = secrets.token_urlsafe(48)
    database.complete_oauth_flow(
        flow_id="flow-1",
        user_id=None,
        github_user={"id": 123, "login": "octocat", "avatar_url": "https://example.com/avatar"},
        encrypted_github_token=cipher.encrypt("github-token-example"),
        github_token_expires_at=int(time.time()) + 3600,
        app_access_token=app_token,
        encrypted_app_access_token=cipher.encrypt(app_token),
        session_expires_at=int(time.time()) + 3600,
    )

    result = database.get_oauth_status("flow-1", poll_token, cipher)
    assert result is not None
    assert result["status"] == "connected"
    assert result["app_access_token"] == app_token

    session = database.get_session(app_token, cipher)
    assert session is not None
    assert session["github_user_id"] == 123
    assert session["github_token"].endswith("example")
