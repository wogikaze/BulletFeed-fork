import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Database
from app.dependencies import get_database
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLETFEED_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    database = Database(tmp_path / "api.db")
    database.initialize()

    def override_database() -> Database:
        return database

    app.dependency_overrides[get_database] = override_database
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/v1/sessions")
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}
