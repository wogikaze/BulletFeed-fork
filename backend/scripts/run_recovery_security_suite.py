"""Repeatable M5 recovery/security selectors. Does not weaken Bandit/Semgrep."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTORS = (
    "tests/test_recovery_security.py",
    "tests/test_release_stack.py",
    "tests/test_replay_recovery.py",
    "tests/test_rss_safety.py",
    "tests/test_json_feed_safety.py",
    "tests/test_web_snapshots.py",
    "tests/test_user_source_subscriptions.py",
    "tests/test_user_interest.py::test_tenant_isolation_and_reset",
    "tests/test_integrated_source_faults.py",
)


def main() -> int:
    command = [sys.executable, "-m", "pytest", "-q", *SELECTORS]
    print(" ".join(command))
    print(
        "residual risks: docker kill/restart and disk-full are host drills, "
        "not this suite; Bandit/Semgrep stay in backend-security CI"
    )
    return subprocess.call(command, cwd=ROOT)  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main())
