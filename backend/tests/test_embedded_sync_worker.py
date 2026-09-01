import threading
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_embedded_sync_worker_does_not_block_health(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BULLETFEED_EMBED_SOURCE_SYNC_WORKER", "1")
    monkeypatch.setenv("BULLETFEED_DATABASE_PATH", str(tmp_path / "embed.db"))
    monkeypatch.setenv("BULLETFEED_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    started = threading.Event()

    async def fake_worker(stop_event=None):
        started.set()
        time.sleep(3)
        if stop_event is not None:
            stop_event.wait(timeout=1)

    monkeypatch.setattr("app.release_worker.run_release_worker", fake_worker)
    try:
        with TestClient(app) as client:
            assert started.wait(timeout=2)
            started_at = time.monotonic()
            response = client.get("/health")
            elapsed = time.monotonic() - started_at
            assert response.status_code == 200
            assert elapsed < 1.5
    finally:
        get_settings.cache_clear()
