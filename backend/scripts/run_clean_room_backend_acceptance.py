"""Run the M7 clean-room backend journey and optional Android release client."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SCRIPTS = BACKEND / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_process_recovery_drill import (  # noqa: E402
    _free_port,
    _request,
    _start_api,
    _start_worker,
    _stop,
    _wait_for_status,
)

from app.database import Database  # noqa: E402
from app.db.migrations import KNOWN_REVISIONS  # noqa: E402

ANDROID_PACKAGE = "com.bulletfeed.app"
ANDROID_TEST_CLASS = "com.bulletfeed.app.RealBackendAcceptanceTest"
RELEASE_BASE_URL = "https://clean-room.invalid/"


def _verify_representative_upgrade(path: Path) -> bool:
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO users (id, created_at) VALUES ('upgrade-survivor', 1)"
        )
        connection.execute(
            "DELETE FROM schema_migrations WHERE revision_id IN ('17', '18')"
        )
    database.initialize()
    with database.connect() as connection:
        survivor = connection.execute(
            "SELECT 1 FROM users WHERE id = 'upgrade-survivor'"
        ).fetchone()
        revisions = {
            row["revision_id"] for row in connection.execute("SELECT revision_id FROM schema_migrations")
        }
    return survivor is not None and revisions == set(KNOWN_REVISIONS)


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    access_token: str | None = None,
    timeout: float = 8,
) -> tuple[int | None, dict[str, Any]]:
    status, body = _request(
        f"{base_url}{path}",
        method=method,
        payload=payload,
        access_token=access_token,
        timeout=timeout,
    )
    if body:
        decoded = json.loads(body)
    else:
        decoded = {}
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{method} {path} returned a non-object response")
    return status, decoded


def _stage(
    stages: list[dict[str, Any]],
    name: str,
    *,
    ok: bool,
    detail: str,
) -> None:
    stages.append({"stage": name, "ok": ok, "detail": detail})
    if not ok:
        raise RuntimeError(f"{name}: {detail}")


def _emit(result: dict[str, Any], output: Path | None) -> None:
    public_result = dict(result)
    public_result.pop("user_id", None)
    payload = json.dumps(public_result, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")


def _gradle_command(root: Path) -> list[str]:
    if os.name == "nt":
        return [str(root / "gradlew.bat")]
    return ["bash", str(root / "gradlew")]


def _repository_sha(root: Path) -> str | None:
    env_sha = os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha
    git = shutil.which("git")
    if git is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    sha = completed.stdout.strip()
    return sha or None


def _run_gradle(root: Path, arguments: list[str]) -> tuple[int | None, str | None]:
    try:
        completed = subprocess.run(  # noqa: S603
            [*_gradle_command(root), *arguments],
            cwd=str(root),
            check=False,
        )
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return int(completed.returncode), None


def _lifecycle_stage(status: str, reason: str, *, exit_code: int | None = None) -> dict[str, Any]:
    stage: dict[str, Any] = {"status": status, "reason": reason}
    if exit_code is not None:
        stage["exit_code"] = exit_code
    return stage


def _unavailable_lifecycle(reason: str) -> dict[str, Any]:
    return {
        "status": "not_available",
        "runner": "adb",
        "scope": "package install/replace and process relaunch only",
        "install": _lifecycle_stage("not_available", reason),
        "upgrade": _lifecycle_stage("not_available", reason),
        "recovery": _lifecycle_stage("not_available", reason),
    }


def _adb_run(adb: str, serial: str | None, arguments: list[str]) -> int | None:
    command = [adb]
    if serial:
        command.extend(["-s", serial])
    command.extend(arguments)
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    return int(completed.returncode)


def _run_android_lifecycle(
    apk: Path | None,
    previous_apk: Path | None,
    serial: str | None,
) -> dict[str, Any]:
    adb = shutil.which("adb")
    if adb is None:
        return _unavailable_lifecycle("adb is not installed on this runner")
    if apk is None or not apk.is_file():
        return _unavailable_lifecycle("release APK was not assembled")
    if apk.name.endswith("-unsigned.apk"):
        return _unavailable_lifecycle("release APK is unsigned and cannot be installed by adb")
    if _adb_run(adb, serial, ["get-state"]) != 0:
        return _unavailable_lifecycle("no ready Android emulator or device is connected")

    uninstall_code = _adb_run(adb, serial, ["uninstall", ANDROID_PACKAGE])
    if uninstall_code is None:
        return {
            **_unavailable_lifecycle("adb stopped responding before clean install"),
            "status": "failed",
        }
    install_code = _adb_run(adb, serial, ["install", str(apk)])
    install = (
        _lifecycle_stage("recorded", "release APK installed after package removal", exit_code=install_code)
        if install_code == 0
        else _lifecycle_stage("failed", "adb install failed", exit_code=install_code)
    )

    if previous_apk is None or not previous_apk.is_file():
        upgrade = _lifecycle_stage(
            "not_available",
            "a distinct previous APK was not supplied; package replacement was not claimed as an upgrade",
        )
    else:
        _adb_run(adb, serial, ["uninstall", ANDROID_PACKAGE])
        previous_code = _adb_run(adb, serial, ["install", str(previous_apk)])
        current_code = _adb_run(adb, serial, ["install", "-r", str(apk)])
        upgrade_status = "recorded" if previous_code == 0 and current_code == 0 else "failed"
        upgrade = {
            "status": upgrade_status,
            "reason": "previous APK installed, then current release APK replaced it with -r",
            "previous_install_exit_code": previous_code,
            "current_install_exit_code": current_code,
        }

    if install["status"] == "recorded":
        stop_code = _adb_run(adb, serial, ["shell", "am", "force-stop", ANDROID_PACKAGE])
        start_code = _adb_run(
            adb,
            serial,
            ["shell", "am", "start", "-W", "-n", f"{ANDROID_PACKAGE}/.MainActivity"],
        )
        recovery = _lifecycle_stage(
            "recorded" if stop_code == 0 and start_code == 0 else "failed",
            "process force-stop and launcher activity relaunch only; session recovery is not claimed",
        )
        recovery["force_stop_exit_code"] = stop_code
        recovery["start_exit_code"] = start_code
    else:
        recovery = _lifecycle_stage(
            "not_available",
            "process relaunch was not attempted because clean install failed",
        )

    statuses = [install["status"], upgrade["status"], recovery["status"]]
    if "failed" in statuses:
        overall_status = "failed"
    elif all(status == "recorded" for status in statuses):
        overall_status = "recorded"
    else:
        overall_status = "partial"
    return {
        "status": overall_status,
        "runner": "adb",
        "scope": "package install/replace and process relaunch only",
        "install": install,
        "upgrade": upgrade,
        "recovery": recovery,
    }


def _run_android_release_client(
    root: Path,
    base_url: str,
    *,
    run_lifecycle: bool,
    previous_apk: Path | None,
    serial: str | None,
) -> tuple[dict[str, Any], int]:
    acceptance_code, acceptance_error = _run_gradle(
        root,
        [
            ":app:testDebugUnitTest",
            "--tests",
            ANDROID_TEST_CLASS,
            f"-Pbulletfeed.acceptance.baseUrl={base_url}/",
        ],
    )
    acceptance: dict[str, Any] = {
        "status": "passed" if acceptance_code == 0 else "failed",
        "test_class": ANDROID_TEST_CLASS,
        "gradle_exit_code": acceptance_code,
        "backend": "same_clean_room_backend",
    }
    if acceptance_error is not None:
        acceptance["error"] = acceptance_error

    release_code, release_error = _run_gradle(
        root,
        [
            ":app:assembleRelease",
            f"-PBULLETFEED_RELEASE_BASE_URL={RELEASE_BASE_URL}",
        ],
    )
    release_dir = root / "app" / "build" / "outputs" / "apk" / "release"
    release_apk = next(
        (
            candidate
            for candidate in (
                release_dir / "app-release.apk",
                release_dir / "app-release-unsigned.apk",
            )
            if candidate.is_file()
        ),
        None,
    )
    release: dict[str, Any] = {
        "status": "passed" if release_code == 0 and release_apk is not None else "failed",
        "variant": "release",
        "gradle_exit_code": release_code,
        "artifact": release_apk.relative_to(root).as_posix() if release_apk is not None else None,
        "artifact_present": release_apk is not None,
        "signed": release_apk is not None and not release_apk.name.endswith("-unsigned.apk"),
        "base_url": "synthetic_https_placeholder",
    }
    if release_error is not None:
        release["error"] = release_error

    lifecycle = (
        _run_android_lifecycle(release_apk, previous_apk, serial)
        if run_lifecycle
        else _unavailable_lifecycle(
            "not requested; use --run-android-lifecycle with a ready emulator or device"
        )
    )
    critical_pass = acceptance["status"] == "passed" and release["status"] == "passed"
    status = "partial" if critical_pass else "failed"
    if lifecycle["status"] == "failed":
        status = "failed"
    report = {
        "report_version": "m7-clean-room-android-release-client-v1",
        "status": status,
        "completion_gate_pass": False,
        "field_validation": False,
        "acceptance": acceptance,
        "release_build": release,
        "lifecycle": lifecycle,
        "limitations": [
            "The JVM acceptance uses the same ephemeral clean-room backend; "
            "it is not Android field evidence.",
            "The release APK is assembled with a synthetic HTTPS placeholder "
            "and is not network-tested.",
            "A default unsigned release output is package evidence, not a signed field APK.",
            "ADB lifecycle evidence covers package/process operations only; "
            "it does not cover UI, OAuth, session, or credential recovery.",
            "ADB clean install removes this app's package data and is intended only for "
            "a disposable emulator.",
        ],
    }
    return report, 0 if critical_pass and lifecycle["status"] != "failed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--android-release-client",
        action="store_true",
        help="run the existing Android real-backend test and release assembly on this backend",
    )
    parser.add_argument(
        "--run-android-lifecycle",
        action="store_true",
        help="opt in to package install/replace and process relaunch checks through adb",
    )
    parser.add_argument(
        "--require-android-lifecycle",
        action="store_true",
        help="fail if install, upgrade, or recovery lifecycle evidence is unavailable",
    )
    parser.add_argument("--adb-serial", default=os.environ.get("ANDROID_SERIAL"))
    parser.add_argument("--previous-apk", type=Path, default=None)
    args = parser.parse_args(argv)
    workdir = Path(tempfile.mkdtemp(prefix="bulletfeed-clean-room-"))
    database_path = workdir / "data" / "bulletfeed.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(BACKEND) + os.pathsep + env.get("PYTHONPATH", ""),
            "BULLETFEED_ACCEPTANCE_HARNESS": "1",
            "BULLETFEED_DATABASE_PATH": str(database_path),
            "BULLETFEED_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "BULLETFEED_GITHUB_CLIENT_ID": "",
            "BULLETFEED_GITHUB_CLIENT_SECRET": "",
            "BULLETFEED_RSS_ALLOWED_HOSTS": "react.dev",
            "BULLETFEED_WEB_ALLOWED_HOSTS": "cisa.gov,react.dev",
            "BULLETFEED_EMBED_SOURCE_SYNC_WORKER": "0",
            "BULLETFEED_WORKER_IDLE_SECONDS": "0.25",
            "BULLETFEED_WORKER_POLL_SECONDS": "1",
            # Fail live official-RSS fetches quickly so seed-statuspage is not locked out.
            "BULLETFEED_REQUEST_TIMEOUT_SECONDS": "1",
        }
    )
    api = None
    worker = None
    stages: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "acceptance_version": (
            "m7-clean-room-android-release-client-v1"
            if args.android_release_client
            else "m7-clean-room-backend-v1"
        ),
        "mode": (
            "fresh_ephemeral_backend_with_android_release_client"
            if args.android_release_client
            else "fresh_ephemeral_backend"
        ),
        "trace_id": "m7-clean-room",
        "tenant_scope": "single_ephemeral_user",
        "stages": stages,
        "limitations": [
            "source acquisition uses the local acceptance seed fixture; "
            "live OAuth and real user enrollment are excluded"
        ],
    }
    if args.android_release_client:
        result["repository_sha"] = _repository_sha(ROOT)
    try:
        upgrade_path = workdir / "data" / "representative-upgrade.db"
        _stage(
            stages,
            "schema_upgrade",
            ok=_verify_representative_upgrade(upgrade_path),
            detail="representative prior schema upgraded without losing persisted user state",
        )
        api = _start_api(env, port)
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_status(f"{base_url}/health", 200, timeout_seconds=40, label="API health")
        worker = _start_worker(env)
        _wait_for_status(
            f"{base_url}/health/ready",
            200,
            timeout_seconds=40,
            label="worker readiness",
        )
        _stage(stages, "stack", ok=True, detail="fresh database, API, and worker are ready")

        status, session = _json_request(base_url, "/v1/sessions", method="POST", payload={})
        if status != 200 or not session.get("accessToken") or not session.get("userId"):
            _stage(stages, "session", ok=False, detail=f"HTTP {status}")
        access_token = str(session["accessToken"])
        user_id = str(session["userId"])
        result["user_id"] = user_id
        _stage(stages, "session", ok=True, detail="anonymous session persisted")

        status, _ = _json_request(
            base_url,
            "/v1/me/profile",
            method="PUT",
            payload={"occupation": "backend engineer", "interests": ["React"], "region": "jp"},
            access_token=access_token,
        )
        _stage(stages, "onboarding_profile", ok=status == 200, detail=f"HTTP {status}")
        status, topic = _json_request(
            base_url,
            "/v1/me/topics",
            method="POST",
            payload={"name": "React", "type": "technology"},
            access_token=access_token,
        )
        _stage(
            stages,
            "interest",
            ok=status == 201 and topic.get("name") == "React",
            detail=f"HTTP {status}",
        )
        status, onboarding = _json_request(
            base_url,
            "/v1/me/onboarding",
            method="PUT",
            payload={
                "profile": {
                    "occupation": "backend engineer",
                    "interests": ["React"],
                    "region": "jp",
                },
                "topics": ["React", "TypeScript", "Vite", "JavaScript", "Node.js"],
                "connectGithub": False,
            },
            access_token=access_token,
        )
        _stage(
            stages,
            "onboarding_ready",
            ok=status == 200 and onboarding.get("state") == "ready",
            detail=f"HTTP {status}; state={onboarding.get('state')}",
        )

        status, recommendations = _json_request(
            base_url,
            "/v1/me/source-recommendations",
            access_token=access_token,
        )
        items = recommendations.get("items", [])
        rss = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and item.get("family") == "rss_atom"
                and item.get("actionability") == "subscribe"
                and not item.get("discoveryOnly")
            ),
            None,
        )
        _stage(
            stages,
            "discovery",
            ok=status == 200 and rss is not None,
            detail=f"HTTP {status}; candidates={len(items)}",
        )
        status, decision = _json_request(
            base_url,
            f"/v1/me/source-recommendations/{rss['id']}",
            method="POST",
            payload={"decision": "approved"},
            access_token=access_token,
        )
        _stage(
            stages,
            "activation",
            ok=status == 200 and decision.get("recommendationStatus") == "approved",
            detail=f"HTTP {status}",
        )
        status, subscriptions = _json_request(
            base_url,
            "/v1/me/sources",
            access_token=access_token,
        )
        _stage(
            stages,
            "subscription",
            ok=status == 200 and bool(subscriptions.get("items")),
            detail=f"HTTP {status}; subscriptions={len(subscriptions.get('items', []))}",
        )

        status, seeded = _json_request(
            base_url,
            "/__acceptance__/seed-statuspage",
            method="POST",
            payload={"userId": user_id},
            timeout=20,
        )
        event_ids = seeded.get("eventIds", [])
        _stage(
            stages,
            "acquisition",
            ok=status == 200 and bool(event_ids),
            detail=f"HTTP {status}; events={len(event_ids)}",
        )
        _stage(
            stages,
            "projection",
            ok=status == 200 and seeded.get("projectedItemCount", 0) > 0,
            detail=(
                f"HTTP {status}; projected_items={seeded.get('projectedItemCount', 0)}"
            ),
        )
        status, feed = _json_request(
            base_url,
            "/v1/feed?limit=5",
            access_token=access_token,
            timeout=8,
        )
        feed_items = feed.get("items", [])
        first = feed_items[0] if feed_items else {}
        _stage(
            stages,
            "feed",
            ok=status == 200 and bool(feed_items),
            detail=f"HTTP {status}; cards={len(feed_items)}",
        )
        status, detail = _json_request(
            base_url,
            f"/v1/events/{first.get('eventId')}?fromFeedItem={first.get('id')}",
            access_token=access_token,
            timeout=8,
        )
        _stage(
            stages,
            "evidence",
            ok=status == 200 and bool(detail.get("sources")) and bool(detail.get("timeline")),
            detail=f"HTTP {status}; sources={len(detail.get('sources', []))}",
        )
        status, exposure = _json_request(
            base_url,
            "/v1/feed/exposures",
            method="POST",
            payload={
                "items": [
                    {
                        "deliveryId": first.get("deliveryId"),
                        "displayedAt": "2026-08-30T00:00:00Z",
                        "dwellMs": 1_500,
                        "visibleRatio": 0.8,
                        "detailOpened": True,
                    }
                ]
            },
            access_token=access_token,
            timeout=8,
        )
        _stage(
            stages,
            "exposure",
            ok=status == 200 and exposure.get("accepted", 0) > 0,
            detail=f"HTTP {status}; accepted={exposure.get('accepted', 0)}",
        )
        status, _ = _json_request(
            base_url,
            f"/v1/feed/items/{first.get('id')}/feedback",
            method="POST",
            payload={"type": "learned_now"},
            access_token=access_token,
            timeout=8,
        )
        _stage(stages, "feedback", ok=status == 200, detail=f"HTTP {status}")
        status, read = _json_request(
            base_url,
            f"/v1/feed/items/{first.get('id')}/read",
            method="PUT",
            access_token=access_token,
            timeout=8,
        )
        _stage(
            stages,
            "read_state",
            ok=status == 200 and read.get("status") == "read",
            detail=f"HTTP {status}; status={read.get('status')}",
        )
        status, subsequent = _json_request(
            base_url,
            "/v1/feed?status=unread&limit=5",
            access_token=access_token,
            timeout=8,
        )
        unread_ids = {item.get("id") for item in subsequent.get("items", []) if isinstance(item, dict)}
        _stage(
            stages,
            "subsequent_feed",
            ok=status == 200 and first.get("id") not in unread_ids,
            detail=f"HTTP {status}; cards={len(subsequent.get('items', []))}",
        )
        if args.android_release_client:
            result["backend_status"] = "passed"
            android, android_exit_code = _run_android_release_client(
                ROOT,
                base_url,
                run_lifecycle=args.run_android_lifecycle or args.require_android_lifecycle,
                previous_apk=args.previous_apk,
                serial=args.adb_serial,
            )
            result["android"] = android
            result["status"] = android["status"]
            _emit(result, args.output)
            if args.require_android_lifecycle and android["lifecycle"]["status"] != "recorded":
                return 1
            return android_exit_code
        result["status"] = "passed"
        _emit(result, args.output)
        return 0
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        _emit(result, args.output)
        return 1
    finally:
        _stop(api)
        _stop(worker)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
