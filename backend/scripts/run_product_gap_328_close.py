"""Same-SHA close audit for #328. Does not invent PASS for human or 7-day gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.database import Database
from app.evaluation.m1_zero_to_useful import load_persona_manifest, run_qualification
from app.evaluation.product_gap_c1_gates import evaluate_c1_gates
from app.evaluation.product_gap_c2 import evaluate_c2
from app.evaluation.product_gap_c3 import evaluate_c3
from app.evaluation.product_gap_c4 import evaluate_c4
from app.evaluation.product_gap_compare import (
    CompareItem,
    attach_source_coverage,
    compare_modes,
)
from app.evaluation.product_gap_g6 import evaluate_g6_journal
from app.services.multiobjective_ranker import RankerCandidate

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "gold" / "product_gap"
PERSONAS = ROOT / "tests" / "gold" / "m1_personas" / "v01" / "personas.json"
G6_JOURNAL = GOLD / "c1" / "g6_journal.json"


def _compare_from_fixture() -> dict:
    payload = json.loads((GOLD / "c5" / "compare_fixture.json").read_text(encoding="utf-8"))
    items = []
    for row in payload["items"]:
        candidate = RankerCandidate(
            item_id=row["item_id"],
            topic_key=row["topic_key"],
            relation_level=row["relation_level"],
            importance_level=row["importance_level"],
            updated_at=row["published_at"],
        )
        items.append(
            CompareItem(
                item_id=row["item_id"],
                published_at=row["published_at"],
                topic_key=row["topic_key"],
                important_unknown=row["important_unknown"],
                already_known=row["already_known"],
                duplicate=row["duplicate"],
                useful=row["useful"],
                candidate=candidate,
            )
        )
    table = compare_modes(items, followed_topics=set(payload["followed_topics"]), k=payload["k"])
    return items, table


def build_report() -> dict:
    c1_gates = evaluate_c1_gates(GOLD / "c1")
    g6 = evaluate_g6_journal(G6_JOURNAL)
    items, compare = _compare_from_fixture()
    compare = attach_source_coverage(compare, g3=c1_gates["g3"])
    c2 = evaluate_c2(GOLD / "c2", items)
    field = (
        json.loads((GOLD / "c5" / "field_journal.json").read_text(encoding="utf-8"))
        if (GOLD / "c5" / "field_journal.json").exists()
        else {"status": "not_started", "people": 0}
    )
    personas = load_persona_manifest(PERSONAS)
    reason_missing = None
    try:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            index = 0

            def factory() -> Database:
                nonlocal index
                index += 1
                database = Database(Path(directory) / f"p{index}.db")
                database.initialize()
                return database

            m1 = run_qualification(factory, personas)
            reason_missing = int(m1.get("display_reason_missing") or 0)
    except Exception as exc:  # noqa: BLE001 - close audit must still emit
        m1 = {"error": str(exc)}
        reason_missing = None

    ubh = int(compare["modes"]["bulletfeed"]["metrics"]["unknown_but_hidden"])
    c3 = evaluate_c3(GOLD / "c3", unknown_but_hidden=ubh)
    c4 = evaluate_c4(GOLD / "c4", persona_reason_missing=reason_missing)
    c5_failures = []
    if int(field.get("people") or 0) < 5 or field.get("status") != "completed":
        c5_failures.append("field_week_lt_5_people")
    if c1_gates["g3"].get("live_oracle_unmeasured"):
        c5_failures.append("rss_oracle_live_unmeasured")
    c5_pass = not c5_failures
    c1_failures = list(c1_gates["g0"]["failures"])
    for name in ("g1", "g2", "g3", "g4", "g5"):
        c1_failures.extend(c1_gates[name].get("failures") or [])
    c1_failures.extend(g6["failures"])
    challenges = {
        "c1_source": {
            "g0": c1_gates["g0"],
            "g1": c1_gates["g1"],
            "g2": c1_gates["g2"],
            "g3": c1_gates["g3"],
            "g4": c1_gates["g4"],
            "g5": c1_gates["g5"],
            "g6": g6,
            "pass": bool(c1_gates["passed"] and g6["pass"]),
            "failures": c1_failures,
        },
        "c2_recommend": c2,
        "c3_knownness": c3,
        "c4_relation": c4,
        "c5_product": {
            "compare_table": compare,
            "field": field,
            "pass": c5_pass,
            "failures": c5_failures,
        },
    }
    all_pass = all(item["pass"] for item in challenges.values())
    return {
        "report_version": "product-gap-328-close-v1",
        "completion_gate_pass": all_pass,
        "challenges": challenges,
        "m1_reason": {"display_reason_missing": reason_missing, "m1": m1},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=GOLD / "close_report.json")
    args = parser.parse_args(argv)
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"completion_gate_pass": report["completion_gate_pass"], "output": str(args.output)}, indent=2
        )
    )
    if args.check:
        return 0 if report["completion_gate_pass"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
