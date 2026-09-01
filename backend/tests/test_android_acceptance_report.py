import json
from pathlib import Path

from scripts.run_real_backend_android_acceptance import _emit

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_android_acceptance_report_is_machine_readable(tmp_path, capsys) -> None:
    output = tmp_path / "android-acceptance.json"
    report = {
        "acceptance_version": "m4-real-backend-android-v1",
        "mode": "fresh_ephemeral_backend",
        "backend_health": "passed",
        "gradle_exit_code": 0,
        "status": "passed",
    }

    _emit(report, output)

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == report
    assert json.loads(capsys.readouterr().out) == report


def test_android_acceptance_disables_embedded_sync_worker() -> None:
    source = (SCRIPTS / "run_real_backend_android_acceptance.py").read_text(encoding="utf-8")
    assert 'BULLETFEED_EMBED_SOURCE_SYNC_WORKER"] = "0"' in source
