from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAIVERS_PATH = ROOT / "backend/security/bandit_waivers.json"


def _normalized_filename(raw: str) -> str:
    path = Path(raw)
    if path.is_absolute():
        try:
            path = path.relative_to(ROOT)
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _finding_key(finding: dict) -> tuple[str, str, int]:
    return (
        _normalized_filename(str(finding["filename"])),
        str(finding["test_id"]),
        int(finding["line_number"]),
    )


def main() -> int:
    waiver_doc = json.loads(WAIVERS_PATH.read_text(encoding="utf-8"))
    waivers = waiver_doc.get("waivers", [])
    expected: dict[tuple[str, str, int], str] = {}
    for waiver in waivers:
        key = (
            str(waiver["filename"]),
            str(waiver["test_id"]),
            int(waiver["line_number"]),
        )
        if key in expected:
            raise SystemExit(f"duplicate Bandit waiver: {key}")
        expected[key] = str(waiver["reason"])

    process = subprocess.run(
        [sys.executable, "-m", "bandit", "-r", "backend/app", "-f", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode not in {0, 1}:
        sys.stderr.write(process.stderr)
        sys.stderr.write(process.stdout)
        return process.returncode

    try:
        report = json.loads(process.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(process.stderr)
        sys.stderr.write(process.stdout)
        return 2

    findings = report.get("results", [])
    seen: set[tuple[str, str, int]] = set()
    unexpected: list[dict] = []
    for finding in findings:
        key = _finding_key(finding)
        if key in expected:
            seen.add(key)
        else:
            unexpected.append(finding)

    stale = sorted(set(expected) - seen)
    if unexpected or stale:
        if unexpected:
            print("Unexpected Bandit findings:", file=sys.stderr)
            for finding in unexpected:
                key = _finding_key(finding)
                print(
                    f"- {key[0]}:{key[2]} {key[1]} {finding.get('issue_text', '')}",
                    file=sys.stderr,
                )
        if stale:
            print("Stale or moved Bandit waivers (re-review before updating):", file=sys.stderr)
            for filename, test_id, line_number in stale:
                print(f"- {filename}:{line_number} {test_id}", file=sys.stderr)
        return 1

    print(
        f"Bandit gate OK: {len(findings)} reviewed findings, "
        f"waiver set {waiver_doc.get('version', 'unknown')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
