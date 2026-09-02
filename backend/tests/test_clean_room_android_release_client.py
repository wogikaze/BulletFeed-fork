from pathlib import Path

import pytest

import scripts.run_clean_room_backend_acceptance as clean_room


def test_lifecycle_contract_does_not_claim_unavailable_evidence() -> None:
    report = clean_room._unavailable_lifecycle("runner not configured")

    assert report["status"] == "not_available"
    assert report["runner"] == "adb"
    assert report["scope"] == "package install/replace and process relaunch only"
    assert report["install"]["status"] == "not_available"
    assert report["upgrade"]["status"] == "not_available"
    assert report["recovery"]["status"] == "not_available"


def test_android_release_client_reuses_acceptance_and_marks_lifecycle_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_apk = (
        tmp_path / "app" / "build" / "outputs" / "apk" / "release" / "app-release-unsigned.apk"
    )

    def fake_gradle(root: Path, arguments: list[str]) -> tuple[int, str | None]:
        if ":app:assembleRelease" in arguments:
            release_apk.parent.mkdir(parents=True)
            release_apk.write_bytes(b"test-apk")
        return 0, None

    monkeypatch.setattr(clean_room, "_run_gradle", fake_gradle)
    monkeypatch.setattr(clean_room.shutil, "which", lambda _: None)

    report, exit_code = clean_room._run_android_release_client(
        tmp_path,
        "http://127.0.0.1:12345",
        run_lifecycle=True,
        previous_apk=None,
        serial=None,
        allow_adb_data_wipe=False,
    )

    assert exit_code == 0
    assert report["status"] == "partial"
    assert report["completion_gate_pass"] is False
    assert report["field_validation"] is False
    assert report["acceptance"]["status"] == "passed"
    assert report["acceptance"]["test_class"] == clean_room.ANDROID_TEST_CLASS
    assert report["acceptance"]["backend"] == "same_clean_room_backend"
    assert report["release_build"]["status"] == "passed"
    assert report["release_build"]["artifact_present"] is True
    assert report["release_build"]["artifact"] == "app/build/outputs/apk/release/app-release-unsigned.apk"
    assert report["release_build"]["signed"] is False
    assert report["lifecycle"]["status"] == "not_available"
    assert all(
        report["lifecycle"][stage]["status"] == "not_available"
        for stage in ("install", "upgrade", "recovery")
    )
    assert "user_id" not in str(report)


def test_android_lifecycle_records_package_operations_without_claiming_upgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    apk = tmp_path / "app-release.apk"
    apk.write_bytes(b"current")
    monkeypatch.setattr(clean_room.shutil, "which", lambda _: "adb")
    monkeypatch.setattr(
        clean_room,
        "_adb_run",
        lambda *_args: {"status": "recorded", "exit_code": 0, "stdout": "1", "stderr": None},
    )

    report = clean_room._run_android_lifecycle(apk, None, None, allow_adb_data_wipe=True)

    assert report["status"] == "partial"
    assert report["install"]["status"] == "recorded"
    assert report["upgrade"]["status"] == "not_available"
    assert report["recovery"]["status"] == "recorded"


def test_adb_timeout_is_failed_with_bounded_reason(monkeypatch) -> None:
    def timeout(*_args, **_kwargs):
        raise clean_room.subprocess.TimeoutExpired(["adb"], 20, stderr="x" * 1000)

    monkeypatch.setattr(clean_room.subprocess, "run", timeout)

    result = clean_room._adb_run("adb", None, ["get-state"])

    assert result["status"] == "failed"
    assert result["failure_kind"] == "timeout"
    assert len(result["stderr"]) <= clean_room.ADB_REASON_LIMIT


def test_adb_os_error_is_failed(monkeypatch) -> None:
    def launch_error(*_args, **_kwargs):
        raise OSError("process launch denied")

    monkeypatch.setattr(clean_room.subprocess, "run", launch_error)

    result = clean_room._adb_run("adb", None, ["get-state"])

    assert result["status"] == "failed"
    assert result["failure_kind"] == "os_error"
    assert "could not execute" in result["reason"]


def test_require_lifecycle_requires_android_client() -> None:
    with pytest.raises(SystemExit) as error:
        clean_room.main(["--require-android-lifecycle"])

    assert error.value.code == 2


def test_lifecycle_refuses_real_device_without_uninstall(monkeypatch, tmp_path: Path) -> None:
    apk = tmp_path / "app-release.apk"
    apk.write_bytes(b"current")
    calls: list[list[str]] = []

    def adb(_adb: str, _serial: str | None, arguments: list[str]) -> dict:
        calls.append(arguments)
        if arguments == ["get-state"]:
            return {"status": "recorded", "exit_code": 0, "stdout": "device", "stderr": None}
        return {"status": "recorded", "exit_code": 0, "stdout": "0", "stderr": None}

    monkeypatch.setattr(clean_room.shutil, "which", lambda _: "adb")
    monkeypatch.setattr(clean_room, "_adb_run", adb)

    report = clean_room._run_android_lifecycle(apk, None, None, allow_adb_data_wipe=True)

    assert report["status"] == "not_available"
    assert "real device" in report["install"]["reason"]
    assert not any(arguments[:1] == ["uninstall"] for arguments in calls)


def test_upgrade_uses_replacement_without_claiming_data_retention(monkeypatch, tmp_path: Path) -> None:
    previous = tmp_path / "previous.apk"
    current = tmp_path / "current.apk"
    previous.write_bytes(b"previous")
    current.write_bytes(b"current")
    calls: list[list[str]] = []

    def adb(_adb: str, _serial: str | None, arguments: list[str]) -> dict:
        calls.append(arguments)
        stdout = "1" if arguments == ["shell", "getprop", "ro.kernel.qemu"] else "device"
        return {"status": "recorded", "exit_code": 0, "stdout": stdout, "stderr": None}

    def identity(path: Path) -> dict:
        return {
            "status": "recorded",
            "package": clean_room.ANDROID_PACKAGE,
            "version_code": "1" if path == previous else "2",
        }

    monkeypatch.setattr(clean_room.shutil, "which", lambda _: "adb")
    monkeypatch.setattr(clean_room, "_adb_run", adb)
    monkeypatch.setattr(clean_room, "_apk_identity", identity)

    report = clean_room._run_android_lifecycle(
        current,
        previous,
        None,
        allow_adb_data_wipe=True,
    )

    assert report["upgrade"]["status"] == "not_available"
    assert report["upgrade"]["validation"] == "package_replacement_only"
    assert ["install", "-r", str(previous)] in calls
    assert ["install", "-r", str(current)] in calls
    assert sum(arguments[:1] == ["uninstall"] for arguments in calls) == 1
