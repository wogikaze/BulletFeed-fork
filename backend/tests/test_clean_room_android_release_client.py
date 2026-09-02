from pathlib import Path

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
    monkeypatch.setattr(clean_room, "_adb_run", lambda *_args: 0)

    report = clean_room._run_android_lifecycle(apk, None, None)

    assert report["status"] == "partial"
    assert report["install"]["status"] == "recorded"
    assert report["upgrade"]["status"] == "not_available"
    assert report["recovery"]["status"] == "recorded"
