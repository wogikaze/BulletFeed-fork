"""Build the versioned #283 longitudinal sample from the existing live 200 set."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.evaluation.longitudinal_qualification import PROTOCOL_VERSION

BACKEND = Path(__file__).resolve().parents[1]
LIVE = BACKEND / "tests" / "gold" / "source_qualification" / "v01" / "live_sample_200_report.json"
OUTPUT = BACKEND / "tests" / "gold" / "source_qualification" / "v01" / "longitudinal_protocol.json"
PER_FAMILY = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, default=LIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    live = json.loads(args.live.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in live["endpoints"]:
        if row.get("outcome") != "success":
            continue
        grouped[str(row["source_family"])].append(row)
    sample: list[dict[str, Any]] = []
    for family in sorted(grouped):
        for row in grouped[family][:PER_FAMILY]:
            sample.append(
                {
                    "source_id": row["source_id"],
                    "source_family": row["source_family"],
                    "fetch_url": row["fetch_url"],
                    "t0_final_url": row.get("final_url"),
                    "t0_content_hash": row.get("live_content_hash"),
                    "t0_content_type": row.get("content_type"),
                    "t0_status_code": row.get("status_code"),
                }
            )
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "parent_issue": 283,
        "t0_source": "m3-live-source-qualification-v1",
        "windows": ["t0_recorded_live_sample", "t1_repeat_fetch"],
        "minimum_observations_per_source": 2,
        "per_family_cap": PER_FAMILY,
        "sample_count": len(sample),
        "source_family_counts": {
            family: sum(1 for row in sample if row["source_family"] == family)
            for family in sorted({row["source_family"] for row in sample})
        },
        "rules": [
            "Do not synthesize an update from a missing second fetch.",
            "Preserve acquisition time, final URL, content type, content hash, and validator headers.",
            "Do not store full public page bodies in this artifact.",
            "Keep live t1 collection out of ordinary PR CI.",
            "Observed timeout/5xx/identity-change belong to remediation.",
            "Zero observed failures are remediation_not_required.",
        ],
        "sample": sample,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sample_count": payload["sample_count"], "families": payload["source_family_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
