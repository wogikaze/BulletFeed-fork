import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import app.services.github as github_service
from app.config import get_settings
from app.database import Database
from app.db.seed import DEMO_REPOSITORIES
from app.dependencies import get_database
from app.main import app
from app.security import TokenCipher


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLETFEED_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    database = Database(tmp_path / "api.db")
    database.initialize()
    yield database
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def mock_github_repositories(monkeypatch):
    async def _mock_list_repositories(settings, token):
        del settings
        del token
        return DEMO_REPOSITORIES

    monkeypatch.setattr(github_service, "list_repositories", _mock_list_repositories)


@pytest.fixture
def client(database):
    def override_database() -> Database:
        return database

    app.dependency_overrides[get_database] = override_database
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _github_token() -> str:
    return "ghp_test_token"


@pytest.fixture
def auth_headers(client: TestClient, database: Database) -> dict[str, str]:
    response = client.post("/v1/sessions")
    assert response.status_code == 200
    body = response.json()
    access_token = body["accessToken"]
    user_id = body["userId"]

    settings = get_settings()
    cipher = TokenCipher(settings.token_encryption_key.get_secret_value())
    now = int(time.time())
    with database.connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO github_connections (
                github_user_id, login, github_token_encrypted, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (123, "testuser", cipher.encrypt(_github_token()), now),
        )
        connection.execute(
            "UPDATE users SET github_connected = 1, github_user_id = ?, github_login = ? WHERE id = ?",
            (123, "testuser", user_id),
        )

    return {"Authorization": f"Bearer {access_token}"}
