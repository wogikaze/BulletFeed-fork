"""Run a repeatable API/worker process-boundary recovery drill."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

BACKEND = Path(__file__).resolve().parents[1]
READY_TIMEOUT_SECONDS = 40.0
POLL_SECONDS = 0.25


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    access_token: str | None = None,
) -> tuple[int | None, bytes]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if access_token is not None:
        headers["Authorization"] = f"Bearer {access_token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return None, b""


def _wait_for_status(
    url: str,
    expected: int | None,
    *,
    timeout_seconds: float,
    label: str,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status, _ = _request(url)
        if status == expected:
            return
        time.sleep(POLL_SECONDS)
    raise RuntimeError(f"{label} did not reach HTTP {expected}")


def _start_api(env: dict[str, str], port: int) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603
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
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _start_worker(env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "app.release_worker"],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _user_exists(database_path: Path, user_id: str) -> bool:
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            "SELECT 1 FROM users WHERE id = ?",
            (user_id,),
        ).fetchone() is not None


def _emit(result: dict[str, Any], output: Path | None) -> None:
    public_result = dict(result)
    public_result.pop("database_path", None)
    public_result.pop("session_user_id", None)
    payload = json.dumps(public_result, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    workdir = Path(tempfile.mkdtemp(prefix="bulletfeed-process-recovery-"))
    database_path = workdir / "data" / "bulletfeed.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(BACKEND) + os.pathsep + env.get("PYTHONPATH", ""),
            "BULLETFEED_DATABASE_PATH": str(database_path),
            "BULLETFEED_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "BULLETFEED_GITHUB_CLIENT_ID": "",
            "BULLETFEED_GITHUB_CLIENT_SECRET": "",
            "BULLETFEED_WORKER_IDLE_SECONDS": "0.25",
            "BULLETFEED_WORKER_POLL_SECONDS": "1",
        }
    )
    api: subprocess.Popen[bytes] | None = None
    worker: subprocess.Popen[bytes] | None = None
    result: dict[str, Any] = {
        "drill_version": "m5-process-recovery-v1",
        "database_path": str(database_path),
        "worker_restart": False,
        "api_restart": False,
        "session_persisted": False,
        "residual_risks": ["disk_full_and_partial_filesystem_write_require_host-specific drills"],
    }
    try:
        api = _start_api(env, port)
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_status(
            f"{base_url}/health",
            200,
            timeout_seconds=READY_TIMEOUT_SECONDS,
            label="API health",
        )
        worker = _start_worker(env)
        _wait_for_status(
            f"{base_url}/health/ready",
            200,
            timeout_seconds=READY_TIMEOUT_SECONDS,
            label="initial readiness",
        )

        status, body = _request(f"{base_url}/v1/sessions", method="POST", payload={})
        if status != 200:
            raise RuntimeError(f"session creation failed with HTTP {status}")
        session = json.loads(body)
        access_token = session["accessToken"]
        user_id = session["userId"]
        result["session_user_id"] = user_id
        result["session_persisted"] = _user_exists(database_path, user_id)

        _stop(worker)
        worker = None
        _wait_for_status(
            f"{base_url}/health/ready",
            503,
            timeout_seconds=READY_TIMEOUT_SECONDS,
            label="worker outage readiness",
        )
        worker = _start_worker(env)
        _wait_for_status(
            f"{base_url}/health/ready",
            200,
            timeout_seconds=READY_TIMEOUT_SECONDS,
            label="worker restart readiness",
        )
        result["worker_restart"] = True

        status, _ = _request(f"{base_url}/v1/me", access_token=access_token)
        if status != 200:
            raise RuntimeError(f"session lookup after worker restart failed with HTTP {status}")

        _stop(api)
        api = None
        _wait_for_status(
            f"{base_url}/health",
            None,
            timeout_seconds=10.0,
            label="API outage",
        )
        api = _start_api(env, port)
        _wait_for_status(
            f"{base_url}/health/ready",
            200,
            timeout_seconds=READY_TIMEOUT_SECONDS,
            label="API restart readiness",
        )
        status, _ = _request(f"{base_url}/v1/me", access_token=access_token)
        if status != 200 or not _user_exists(database_path, user_id):
            raise RuntimeError(f"session persistence after API restart failed with HTTP {status}")
        result["api_restart"] = True
        result["status"] = "passed"
        _emit(result, args.output)
        return 0
    except Exception as exc:
        result.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        _emit(result, args.output)
        return 1
    finally:
        _stop(api)
        _stop(worker)


if __name__ == "__main__":
    raise SystemExit(main())
