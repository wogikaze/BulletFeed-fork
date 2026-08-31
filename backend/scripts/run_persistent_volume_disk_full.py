"""Fault-inject disk-full on a loop-mounted ext4 volume, not tmpfs.

This is the M5 persistent-volume drill. Bounded tmpfs ENOSPC in the host
recovery probe is a different boundary and must not be treated as this result.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.database import Database
from app.services.web_snapshots import (
    RobotsDecision,
    SnapshotStore,
    WebSnapshot,
    content_hash_for,
    snapshot_id_for,
)

DRILL_VERSION = "m5-persistent-volume-disk-full-v1"
VOLUME_SIZE_BYTES = 8 * 1024 * 1024
PROTECTED_BODY = b"protected-lineage-body"
FILL_BODY = b"x" * (4 * 1024 * 1024)


def _snapshot(body: bytes, *, suffix: str) -> WebSnapshot:
    digest = content_hash_for(body)
    url = f"https://pv-disk.example/{suffix}"
    return WebSnapshot(
        snapshot_id=snapshot_id_for(canonical_url=url, content_hash=digest),
        canonical_url=url,
        retrieved_at="2026-08-31T00:00:00Z",
        content_hash=digest,
        status_code=200,
        headers=(("content-type", "text/plain"),),
        body=body,
        etag=None,
        last_modified=None,
        robots=RobotsDecision(
            source_url=url,
            robots_url=None,
            allowed=True,
            reason="pv_disk_full_probe",
            retrieved_at="2026-08-31T00:00:00Z",
        ),
        final_url=url,
    )


def exercise_volume(root: Path) -> dict[str, Any]:
    """Run snapshot + DB invariants against an already-mounted volume root."""
    snapshot_root = root / "snapshots"
    database_path = root / "bulletfeed.db"
    store = SnapshotStore(snapshot_root)
    protected = _snapshot(PROTECTED_BODY, suffix="protected")
    stored = store.put(protected)
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO users (id, created_at) VALUES (?, 0)", ("pv-user",))
        connection.execute(
            """
            INSERT INTO observations (
                id, source_type, source_key, source_observation_id,
                payload_hash, payload_json, original_url, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "obs_pv_protected",
                "generic_web",
                stored.canonical_url,
                "pv-protected",
                stored.content_hash,
                json.dumps({"snapshot_id": stored.snapshot_id}),
                stored.canonical_url,
                stored.retrieved_at,
            ),
        )
        connection.commit()

    write_failed = False
    error_name = ""
    try:
        store.put(_snapshot(FILL_BODY, suffix="overflow"))
    except OSError as exc:
        write_failed = True
        error_name = f"{type(exc).__name__}:{exc.errno}:{errno.errorcode.get(exc.errno or 0, '')}"

    reloaded = store.get(stored.snapshot_id)
    leftover_tmp = [
        path.name for path in snapshot_root.iterdir() if path.name.startswith(".tmp-")
    ]
    with database.connect() as connection:
        row = connection.execute(
            "SELECT payload_json, payload_hash FROM observations WHERE id = ?",
            ("obs_pv_protected",),
        ).fetchone()
        user_row = connection.execute(
            "SELECT id FROM users WHERE id = ?",
            ("pv-user",),
        ).fetchone()

    db_ok = (
        row is not None
        and json.loads(row["payload_json"])["snapshot_id"] == stored.snapshot_id
        and row["payload_hash"] == stored.content_hash
        and user_row is not None
    )
    lineage_ok = (
        reloaded is not None
        and reloaded.body == PROTECTED_BODY
        and reloaded.content_hash == stored.content_hash
        and leftover_tmp == []
        and db_ok
    )
    passed = write_failed and lineage_ok
    return {
        "write_failed": write_failed,
        "error": error_name,
        "protected_snapshot_survived": reloaded is not None and reloaded.body == PROTECTED_BODY,
        "partial_tmp_cleaned": leftover_tmp == [],
        "db_consistent": db_ok,
        "lineage_protected": lineage_ok,
        "status": "passed" if passed else "failed",
        "medium": "persistent_volume",
    }


def loop_ext4_available() -> bool:
    if os.name != "posix":
        return False
    return shutil.which("mkfs.ext4") is not None or shutil.which("sudo") is not None


def _run(command: tuple[str, ...]) -> None:
    completed = subprocess.run(  # noqa: S603
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        suffix = detail[-1][:300] if detail else "no diagnostic output"
        joined = " ".join(command)
        raise RuntimeError(f"{joined} failed: {suffix}")


def _maybe_sudo(command: tuple[str, ...]) -> tuple[str, ...]:
    if os.geteuid() == 0:
        return command
    sudo = shutil.which("sudo")
    if sudo is None:
        return command
    return (sudo, *command)


def run_loop_ext4_drill() -> dict[str, Any]:
    """Create an 8MiB ext4 loop device and exercise disk-full on it."""
    result: dict[str, Any] = {
        "drill_version": DRILL_VERSION,
        "medium": "ext4_loop",
        "tmpfs_substituted": False,
        "status": "failed",
    }
    if not loop_ext4_available():
        result["status"] = "skipped"
        result["skip_reason"] = "loop-mounted ext4 is unavailable on this host"
        return result

    work = Path(tempfile.mkdtemp(prefix="bulletfeed-m5-pv-"))
    image = work / "volume.img"
    mount = work / "mnt"
    mount.mkdir()
    mounted = False
    try:
        image.write_bytes(b"\0" * VOLUME_SIZE_BYTES)
        mkfs = shutil.which("mkfs.ext4")
        mkfs_cmd = (mkfs, "-F", str(image)) if mkfs else ("mkfs.ext4", "-F", str(image))
        _run(_maybe_sudo(mkfs_cmd))
        _run(_maybe_sudo(("mount", "-o", "loop", str(image), str(mount))))
        mounted = True
        if os.geteuid() != 0:
            _run(_maybe_sudo(("chown", "-R", f"{os.getuid()}:{os.getgid()}", str(mount))))
        exercised = exercise_volume(mount)
        result.update(exercised)
        result["medium"] = "ext4_loop"
        result["tmpfs_substituted"] = False
        result["volume_size_bytes"] = VOLUME_SIZE_BYTES
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "failed"
    finally:
        if mounted:
            subprocess.run(  # noqa: S603
                _maybe_sudo(("umount", str(mount))),
                capture_output=True,
                text=True,
                check=False,
            )
        shutil.rmtree(work, ignore_errors=True)
    return result


def _emit(result: dict[str, Any], output: Path | None) -> None:
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    result = run_loop_ext4_drill()
    _emit(result, args.output)
    if result["status"] == "passed":
        return 0
    if result["status"] == "skipped":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
