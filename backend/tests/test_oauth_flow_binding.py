import time

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.config import Settings
from app.routers.auth import github_callback
from app.security import TokenCipher
from app.services.oauth_flow_policy import MAX_ACTIVE_FLOWS_PER_USER, create_user_oauth_flow


def test_legacy_oauth_start_requires_authenticated_user(client):
    response = client.post(
        "/v1/auth/github/start",
        headers={"X-User-Id": "forged-user"},
    )
    assert response.status_code == 401


def test_oauth_flow_policy_cleans_expired_rows_and_caps_per_user(database):
    now = 1_800_000_000
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO users (id, created_at) VALUES ('user_a', 0), ('user_b', 0)"
        )
        connection.execute(
            """
            INSERT INTO oauth_flows (
                flow_id, state_hash, poll_token_hash, pkce_verifier_encrypted,
                user_id, status, expires_at, created_at
            ) VALUES ('expired', 'expired-state', 'expired-poll', 'expired-verifier',
                      'user_a', 'pending', ?, ?)
            """,
            (now - 1, now - 700),
        )

    for index in range(MAX_ACTIVE_FLOWS_PER_USER):
        create_user_oauth_flow(
            database,
            flow_id=f"flow-a-{index}",
            user_id="user_a",
            state=f"state-a-{index}",
            poll_token=f"poll-a-{index}",
            encrypted_verifier=f"verifier-a-{index}",
            expires_at=now + 600,
            now=now,
        )

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM oauth_flows WHERE flow_id = 'expired'"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM oauth_flows WHERE user_id = 'user_a'"
        ).fetchone()["count"] == MAX_ACTIVE_FLOWS_PER_USER

    with pytest.raises(HTTPException) as exc_info:
        create_user_oauth_flow(
            database,
            flow_id="flow-a-over-limit",
            user_id="user_a",
            state="state-a-over-limit",
            poll_token="poll-a-over-limit",
            encrypted_verifier="verifier-a-over-limit",
            expires_at=now + 600,
            now=now,
        )
    assert exc_info.value.status_code == 429

    create_user_oauth_flow(
        database,
        flow_id="flow-b-0",
        user_id="user_b",
        state="state-b-0",
        poll_token="poll-b-0",
        encrypted_verifier="verifier-b-0",
        expires_at=now + 600,
        now=now,
    )


@pytest.mark.asyncio
async def test_callback_rejects_preexisting_unbound_oauth_flow(database):
    key = Fernet.generate_key().decode()
    cipher = TokenCipher(key)
    settings = Settings(
        github_client_id="client-id",
        github_client_secret="client-secret",
        token_encryption_key=key,
    )
    state = "legacy-unbound-state-value-1234567890"
    database.create_oauth_flow(
        flow_id="legacy-unbound",
        user_id=None,
        state=state,
        poll_token="legacy-poll-token",
        encrypted_verifier=cipher.encrypt("legacy-verifier"),
        expires_at=int(time.time()) + 600,
    )

    with pytest.raises(HTTPException) as exc_info:
        await github_callback(
            settings=settings,
            database=database,
            cipher=cipher,
            code="unused-code",
            state_value=state,
        )

    assert exc_info.value.status_code == 400
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status FROM oauth_flows WHERE flow_id = 'legacy-unbound'"
        ).fetchone()
    assert row["status"] == "failed"
