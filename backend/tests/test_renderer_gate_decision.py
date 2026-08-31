from pathlib import Path

from scripts.build_renderer_gate_decision import main


def test_current_qualification_defers_issue_64(tmp_path: Path) -> None:
    output = tmp_path / "renderer_gate_decision.json"
    assert main(["--output", str(output)]) == 0
    payload = output.read_text(encoding="utf-8")
    assert '"close_issue_64": true' in payload
    assert '"start_real_renderer": false' in payload
    assert '"js_render_would_recover_count": 0' in payload
    assert "Playwright" not in payload
