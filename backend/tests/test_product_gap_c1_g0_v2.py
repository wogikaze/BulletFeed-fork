from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from app.evaluation.product_gap_c1 import evaluate_g0, load_g0_sources

GOLD_V2 = Path(__file__).parent / "gold" / "product_gap" / "c1" / "v2"


def test_g0_v2_is_public_coverage_not_ssrf_padding() -> None:
    report = evaluate_g0(GOLD_V2)
    assert report.dataset_version == "product-gap-c1-g0-v2"
    assert report.attested is False
    assert report.source_count >= 300
    assert report.japanese_count >= 100
    assert report.no_rss_web_count >= 60
    assert report.families.get("official_blog", 0) >= 40
    assert report.policy_blocked_count >= 1
    sources = load_g0_sources(GOLD_V2 / "sources.json")
    blocked = [row for row in sources if row.policy_status == "policy_blocked"]
    assert blocked
    for row in blocked:
        host = (urlparse(row.site_url).hostname or "").lower()
        assert host not in {"localhost", "127.0.0.1", "169.254.169.254"}
        assert not host.startswith("192.168.")
        assert "127.0.0.1" not in host
    splits = {}
    for row in sources:
        splits.setdefault(row.registrable_domain, set()).add(row.split)
    assert all(len(values) == 1 for values in splits.values())
    urls = {row.site_url.rstrip("/") for row in sources}
    assert "https://gohugo.io/news" not in urls
    assert "https://zenn.dev" not in urls
    assert "https://qiita.com" not in urls
