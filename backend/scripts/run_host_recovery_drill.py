"""Run an isolated Docker Compose API/worker restart recovery drill."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

BACKEND = Path(__file__).resolve().parents[1]
COMPOSE_SOURCE = BACKEND / "compose.release.yml"
DEFAULT_TIMEOUT_SECONDS = 120.0
POLL_SECONDS = 1.0
STORAGE_FAULT_PROBE = """
from pathlib import Path
from app.services.web_snapshots import (
    RobotsDecision,
    SnapshotStore,
    WebSnapshot,
    content_hash_for,
    snapshot_id_for,
)

root = Path("/tmp/m5-snapshot-fault")
store = SnapshotStore(root)
body = b"x" * (128 * 1024)
snapshot = WebSnapshot(
    snapshot_id=snapshot_id_for(
        canonical_url="https://fault.example/snapshot",
        content_hash=content_hash_for(body),
    ),
    canonical_url="https://fault.example/snapshot",
    retrieved_at="2026-08-30T00:00:00Z",
    content_hash=content_hash_for(body),
    status_code=200,
    headers=(("content-type", "text/html"),),
    body=body,
    etag=None,
    last_modified=None,
    robots=RobotsDecision(
        source_url="https://fault.example/snapshot",
        robots_url=None,
        allowed=True,
        reason="fault_probe",
        retrieved_at="2026-08-30T00:00:00Z",
    ),
    final_url="https://fault.example/snapshot",
)
try:
    store.put(snapshot)
except OSError:
    assert store.list_ids() == ()
    assert not any(path.name.startswith(".tmp-") for path in root.iterdir())
else:
    raise RuntimeError("expected the bounded tmpfs to reject the snapshot body")
print("filesystem fault probe passed")
""".strip()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _docker_executable() -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("docker executable is not available")
    return executable


def _compose(
    project: str,
    compose_file: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        (
            _docker_executable(),
            "compose",
            "--project-name",
            project,
            "--file",
            str(compose_file),
            *arguments,
        ),
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_compose(project: str, compose_file: Path, *arguments: str) -> None:
    completed = _compose(project, compose_file, *arguments)
    if completed.returncode == 0:
        return
    detail = completed.stderr.strip().splitlines()
    suffix = detail[-1][:300] if detail else "no diagnostic output"
    joined = " ".join(arguments)
    raise RuntimeError(f"docker compose {joined} failed: {suffix}")


def _run_filesystem_fault_probe(project: str, compose_file: Path) -> None:
    _run_compose(
        project,
        compose_file,
        "run",
        "--rm",
        "--no-deps",
        "--mount",
        "type=tmpfs,destination=/tmp,tmpfs-size=65536,tmpfs-mode=1777",
        "api",
        "python",
        "-c",
        STORAGE_FAULT_PROBE,
    )


def _render_compose(path: Path, *, env_file: Path, port: int) -> None:
    content = COMPOSE_SOURCE.read_text(encoding="utf-8")
    content = content.replace(
        "context: .",
        f"context: '{BACKEND.as_posix()}'",
    )
    content = content.replace(
        "env_file: .env.release",
        f"env_file: '{env_file.as_posix()}'",
    )
    content = content.replace(
        "127.0.0.1:8000:8000",
        f"127.0.0.1:{port}:8000",
    )
    path.write_text(content, encoding="utf-8")


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
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return None, b""


def _wait_for_status(url: str, expected: int, *, timeout_seconds: float, label: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status, _ = _request(url)
        if status == expected:
            return
        time.sleep(POLL_SECONDS)
    raise RuntimeError(f"{label} did not reach HTTP {expected}")


def _write_release_env(path: Path, *, database_path: str) -> None:
    path.write_text(
        "\n".join(
            (
                "BULLETFEED_GITHUB_CLIENT_ID=host-recovery-drill",
                "BULLETFEED_GITHUB_CLIENT_SECRET=host-recovery-drill-secret",
                f"BULLETFEED_TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}",
                f"BULLETFEED_DATABASE_PATH={database_path}",
                "BULLETFEED_REQUEST_TIMEOUT_SECONDS=5",
                "BULLETFEED_MAX_RESPONSE_BYTES=1048576",
                "BULLETFEED_WORKER_IDLE_SECONDS=0.25",
                "BULLETFEED_WORKER_POLL_SECONDS=1",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def _emit(result: dict[str, Any], output: Path | None) -> None:
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")


def run_drill(*, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    project = f"bulletfeed-m5-host-{os.getpid()}-{time.time_ns()}"
    result: dict[str, Any] = {
        "drill_version": "m5-host-recovery-v1",
        "runtime": "docker-compose",
        "api_restart": False,
        "worker_restart": False,
        "session_persisted": False,
        "ready_after_restart": False,
        "filesystem_fault_injection": False,
        "status": "failed",
        "residual_risks": [
            "persistent-volume disk-full still requires a host-specific fault drill"
        ],
    }
    with tempfile.TemporaryDirectory(prefix="bulletfeed-m5-host-") as directory:
        root = Path(directory)
        env_file = root / "env.release"
        compose_file = root / "compose.yml"
        port = _free_port()
        _write_release_env(env_file, database_path="/data/bulletfeed.db")
        _render_compose(compose_file, env_file=env_file, port=port)
        base_url = f"http://127.0.0.1:{port}"
        started = True
        try:
            _run_compose(project, compose_file, "up", "-d", "--build")
            _wait_for_status(
                f"{base_url}/health",
                200,
                timeout_seconds=timeout_seconds,
                label="initial API health",
            )
            _wait_for_status(
                f"{base_url}/health/ready",
                200,
                timeout_seconds=timeout_seconds,
                label="initial worker readiness",
            )
            status, body = _request(f"{base_url}/v1/sessions", method="POST", payload={})
            if status != 200:
                raise RuntimeError(f"session creation failed with HTTP {status}")
            session = json.loads(body)
            access_token = session.get("accessToken")
            if not isinstance(access_token, str) or not access_token:
                raise RuntimeError("session response did not contain an access token")

            _run_filesystem_fault_probe(project, compose_file)
            result["filesystem_fault_injection"] = True

            _run_compose(project, compose_file, "restart", "api")
            _wait_for_status(
                f"{base_url}/health/ready",
                200,
                timeout_seconds=timeout_seconds,
                label="API restart readiness",
            )
            status, _ = _request(f"{base_url}/v1/me", access_token=access_token)
            if status != 200:
                raise RuntimeError(f"session lookup after API restart failed with HTTP {status}")
            result["api_restart"] = True
            result["session_persisted"] = True

            _run_compose(project, compose_file, "restart", "worker")
            _wait_for_status(
                f"{base_url}/health/ready",
                200,
                timeout_seconds=timeout_seconds,
                label="worker restart readiness",
            )
            status, _ = _request(f"{base_url}/v1/me", access_token=access_token)
            if status != 200:
                raise RuntimeError(f"session lookup after worker restart failed with HTTP {status}")
            result["worker_restart"] = True
            result["ready_after_restart"] = True
            result["status"] = "passed"
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if started:
                _compose(project, compose_file, "down", "--volumes", "--remove-orphans")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    result = run_drill(timeout_seconds=args.timeout)
    _emit(result, args.output)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
