"""Assemble product-gap-c1-g0-v2. Does not overwrite the v1 development corpus."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_product_gap_c1_g0_corpus import assemble_v2_rows, write_g0_dataset

OUT = ROOT / "tests" / "gold" / "product_gap" / "c1" / "v2"
DATASET = "product-gap-c1-g0-v2"


def main() -> int:
    rows = assemble_v2_rows()
    summary = write_g0_dataset(
        rows,
        dataset_version=DATASET,
        out=OUT,
        final_blind_eligible=True,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    missing = []
    if summary["source_count"] < 310:
        missing.append(f"sources {summary['source_count']}<310")
    if summary["topic_count"] < 24:
        missing.append(f"topics {summary['topic_count']}<24")
    if summary["japanese_count"] < 100:
        missing.append(f"ja {summary['japanese_count']}<100")
    if summary["no_rss_web_count"] < 60:
        missing.append(f"no_rss {summary['no_rss_web_count']}<60")
    if summary["blind_source_ratio"] < 0.30:
        missing.append(f"blind {summary['blind_source_ratio']:.3f}<0.30")
    if summary["policy_blocked_count"] < 1:
        missing.append("policy_blocked missing")
    for family in ("official_blog", "corp_tech_blog", "personal_dev_blog", "docs_changelog", "rss_atom_json"):
        if summary["families"].get(family, 0) < 40:
            missing.append(f"{family} {summary['families'].get(family, 0)}<40")
    loopback = [row["site_url"] for row in rows if "127.0.0.1" in row["site_url"] or row["domain"] in {"localhost", "169.254.169.254"}]
    if loopback:
        missing.append("loopback_in_g0")
    if missing:
        raise SystemExit("G0 v2 floors unmet: " + "; ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
