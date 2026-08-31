"""Record the #64 real-renderer start/defer decision from M3 qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.evaluation.real_renderer_gate import evaluate_real_renderer_gate

BACKEND = Path(__file__).resolve().parents[1]
REPORT = BACKEND / "tests" / "gold" / "source_qualification" / "v01" / "report.json"
OUTPUT = BACKEND / "tests" / "gold" / "source_qualification" / "v01" / "renderer_gate_decision.json"


def _js_recover_count(report: dict[str, Any]) -> int:
    metrics = report.get("source_family_metrics") or {}
    return sum(int(family.get("js_render_would_recover_count") or 0) for family in metrics.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    js_recover = _js_recover_count(report)
    if js_recover:
        raise SystemExit("refusing to defer #64 while js_render_would_recover_count > 0")
    decision = evaluate_real_renderer_gate(
        (),
        live_endpoint_count=int(report["live_endpoint_count"]),
        replay_case_count=int(report["replay_case_count"]),
    )
    payload = {
        "decision_version": decision.policy_version,
        "label_source": "live_qualification",
        "human_gold": False,
        "blind_read": False,
        "live_endpoint_count": report["live_endpoint_count"],
        "replay_case_count": report["replay_case_count"],
        "replay_failed_count": report.get("replay_failed_count"),
        "js_render_would_recover_count": js_recover,
        "start_real_renderer": decision.start_real_renderer,
        "close_issue_64": decision.close_issue_64,
        "issue_64_remains_open": decision.issue_64_remains_open,
        "persistent_primary_need_count": decision.persistent_primary_need_count,
        "e2e_js_only_recall_loss": decision.e2e_js_only_recall_loss,
        "reasons": list(decision.reasons),
        "reopen_when": [
            ">=5 recurring live primary sources need JS after successful static fetch",
            "or JS-only misses lower important-unknown recall by >=5 percentage points",
        ],
        "browser_not_introduced": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if decision.close_issue_64 else 1


if __name__ == "__main__":
    raise SystemExit(main())
