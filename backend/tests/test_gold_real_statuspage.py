import json
from pathlib import Path

import pytest

from app.evaluation.gold import evaluate_statuspage_bundle
from app.evaluation.release_gate import require_release_gate


@pytest.mark.parametrize(
    ("filename", "bundle_id"),
    (
        ("statuspage_github_actions_20260806.json", "statuspage-github-actions-20260806"),
        ("statuspage_github_copilot_20260803.json", "statuspage-github-copilot-20260803"),
    ),
)
def test_real_github_status_bundle_passes_release_gate(
    database,
    filename: str,
    bundle_id: str,
) -> None:
    path = Path(__file__).parent / "gold" / filename
    bundle = json.loads(path.read_text(encoding="utf-8"))

    assert bundle["provenance"]["source_url"] == "https://www.githubstatus.com/api/v2/incidents.json"
    assert bundle["provenance"]["captured_from_live_api"] is True

    report = evaluate_statuspage_bundle(database, bundle)

    assert report.bundle_id == bundle_id
    assert report.revision_accuracy == 1.0
    assert report.delta_precision == 1.0
    assert report.delta_recall == 1.0
    assert report.repetition_rate == 0.0
    assert report.correction_recall == 1.0
    assert report.evidence_coverage == 1.0
    assert report.unsupported_claim_count == 0
    assert report.false_merge_count == 0
    assert report.false_split_count == 0
    require_release_gate(report)
