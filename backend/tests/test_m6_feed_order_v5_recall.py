import json
from pathlib import Path

REPORT = (
    Path(__file__).resolve().parent
    / "gold"
    / "m6"
    / "v01"
    / "cluster_recall_after_feed_order_v5.json"
)


def test_feed_order_v5_remeasure_does_not_claim_top3_iu_gain() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload["report_version"] == "m6-cluster-recall-after-feed-order-v5"
    assert payload["blind_read"] is False
    assert payload["blind_records_loaded"] is False
    assert payload["ranking_contract_version"] == "feed-order-v5"
    for row in payload["persona_families"].values():
        assert row["iu_recall_at_10_delta_vs_frozen"] == 0.0
    after_identity = payload["headline_at_10"]["after_identity"][
        "important_unknown_recall_at_10"
    ]
    after_v5 = payload["headline_at_10"]["after_feed_order_v5"][
        "important_unknown_recall_at_10"
    ]
    assert after_v5 < after_identity
