import json
from pathlib import Path

from scripts import run_host_recovery_drill


def test_render_compose_uses_isolated_paths_and_port(tmp_path: Path) -> None:
    env_file = tmp_path / "env.release"
    compose_file = tmp_path / "compose.yml"
    run_host_recovery_drill._write_release_env(env_file, database_path="/data/bulletfeed.db")
    run_host_recovery_drill._render_compose(compose_file, env_file=env_file, port=48123)

    rendered = compose_file.read_text(encoding="utf-8")
    assert f"context: '{run_host_recovery_drill.BACKEND.as_posix()}'" in rendered
    assert f"env_file: '{env_file.as_posix()}'" in rendered
    assert "127.0.0.1:48123:8000" in rendered
    assert "127.0.0.1:8000:8000" not in rendered


def test_main_persists_passed_host_recovery_result(tmp_path: Path, monkeypatch) -> None:
    expected = {
        "drill_version": "m5-host-recovery-v1",
        "runtime": "docker-compose",
        "api_restart": True,
        "worker_restart": True,
        "session_persisted": True,
        "ready_after_restart": True,
        "status": "passed",
        "residual_risks": [],
    }

    def fake_run_drill(*, timeout_seconds: float) -> dict:
        assert timeout_seconds == 12
        return expected

    monkeypatch.setattr(run_host_recovery_drill, "run_drill", fake_run_drill)
    output = tmp_path / "host-recovery.json"

    assert run_host_recovery_drill.main(["--timeout", "12", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == expected
