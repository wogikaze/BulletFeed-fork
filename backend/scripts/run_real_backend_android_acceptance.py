"""Start ephemeral FastAPI+SQLite and run Android real-backend acceptance tests.

Does not read or print GitHub OAuth secrets, bearer tokens, or refresh tokens.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, timeout_seconds: float = 30.0) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + timeout_seconds
    last_error = "not started"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 300:
                    return
                last_error = f"status {response.status}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = type(exc).__name__
        time.sleep(0.2)
    raise RuntimeError(f"Acceptance harness did not become healthy ({last_error})")


def _gradle_command(root: Path) -> list[str]:
    if os.name == "nt":
        return [str(root / "gradlew.bat")]
    return ["bash", str(root / "gradlew")]


def main() -> int:
    root = _repo_root()
    backend = _backend_dir()
    port = _free_port()
    workdir = Path(tempfile.mkdtemp(prefix="bulletfeed-acceptance-"))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend) + os.pathsep + env.get("PYTHONPATH", "")
    env["BULLETFEED_ACCEPTANCE_HARNESS"] = "1"
    env["BULLETFEED_DATABASE_PATH"] = str(workdir / "acceptance.db")
    env["BULLETFEED_TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    env["BULLETFEED_GITHUB_CLIENT_ID"] = ""
    env["BULLETFEED_GITHUB_CLIENT_SECRET"] = ""
    env["BULLETFEED_RSS_ALLOWED_HOSTS"] = "react.dev"
    env["BULLETFEED_WEB_ALLOWED_HOSTS"] = "react.dev,cisa.gov"
    env.pop("BULLETFEED_ACCEPTANCE_BASE_URL", None)

    process = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(workdir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_health(port)
        gradle = _gradle_command(root)
        result = subprocess.run(  # noqa: S603
            [
                *gradle,
                ":app:testDebugUnitTest",
                "--tests",
                "com.bulletfeed.app.RealBackendAcceptanceTest",
                f"-Pbulletfeed.acceptance.baseUrl=http://127.0.0.1:{port}/",
            ],
            cwd=str(root),
            check=False,
        )
        return int(result.returncode)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
