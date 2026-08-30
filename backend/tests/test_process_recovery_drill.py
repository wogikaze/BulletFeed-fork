import json
from pathlib import Path

from scripts.run_process_recovery_drill import _emit


def test_recovery_evidence_omits_ephemeral_identity_fields(tmp_path: Path, capsys) -> None:
    output = tmp_path / "recovery.json"
    _emit(
        {
            "drill_version": "m5-process-recovery-v1",
            "database_path": "C:/temporary/secret-path/bulletfeed.db",
            "session_user_id": "usr_ephemeral",
            "worker_restart": True,
            "api_restart": True,
            "session_persisted": True,
            "status": "passed",
        },
        output,
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "passed"
    assert "database_path" not in persisted
    assert "session_user_id" not in persisted
    assert json.loads(capsys.readouterr().out) == persisted
