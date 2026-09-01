"""Challenge-1 G1–G5 evaluation. Does not feed gold into production, or invent PASS."""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import feedparser

from app.evaluation.product_gap_c1 import G0Source, evaluate_g0, load_g0_sources
from app.evaluation.product_gap_ssrf import evaluate_ssrf_suite
from app.services.rss_article_enrichment import enrich_html_bytes, is_summary_only
from app.services.rss_pipeline import ingest_feed_events
from app.services.source_discovery import (
    discover_sources_for_topics,
    source_candidate_allows_claim_evidence,
)
from app.services.source_feed_discover import extract_alternate_feed_links, well_known_feed_urls
from app.services.source_registry import SourceRegistry, canonicalize_url
from app.services.web_snapshots import RobotsDecision

GOLD_C1 = Path(__file__).resolve().parents[2] / "tests" / "gold" / "product_gap" / "c1"
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
_ITEM_RE = re.compile(r"<item\b[^>]*>(.*?)</item>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<link\b[^>]*>(.*?)</link>", re.IGNORECASE | re.DOTALL)


def _canonical(url: str) -> str:
    try:
        return canonicalize_url(url)
    except ValueError:
        return url.rstrip("/")


def production_feed_candidates(site_url: str, *, html: str | None = None) -> list[str]:
    """Same candidate sources production uses before HTTP confirm: HTML alternate + 16 probes."""
    found: list[str] = []
    seen: set[str] = set()
    if html:
        for link in extract_alternate_feed_links(html, page_url=site_url):
            key = _canonical(link.href)
            if key not in seen:
                seen.add(key)
                found.append(key)
    for probe in well_known_feed_urls(site_url):
        key = _canonical(probe)
        if key not in seen:
            seen.add(key)
            found.append(key)
    return found


def _load_floors(gold_dir: Path) -> dict[str, float]:
    freeze = json.loads((gold_dir / "g0_freeze.json").read_text(encoding="utf-8"))
    return {str(key): float(value) for key, value in freeze["metrics"].items()}


def _precision_at_k(candidates: list[str], gold: str, *, k: int = 3) -> float:
    window = candidates[:k]
    if not window:
        return 0.0
    return sum(1 for item in window if item == gold) / len(window)


def evaluate_g1(
    sources: list[G0Source],
    *,
    floors: dict[str, float],
    fixtures: Path | None = None,
) -> dict[str, Any]:
    fixture_root = fixtures or FIXTURES
    eligible_feed = [
        row
        for row in sources
        if row.has_feed and row.feed_url and row.policy_status == "eligible"
    ]
    precisions: list[float] = []
    hits = 0
    family_hits: dict[str, list[int]] = defaultdict(list)
    ja_hits: list[int] = []
    undiscovered: list[dict[str, str]] = []
    for row in eligible_feed:
        gold = _canonical(row.feed_url or "")
        candidates = production_feed_candidates(row.site_url)
        hit = gold in set(candidates)
        hits += int(hit)
        family_hits[row.family].append(int(hit))
        if row.language == "ja":
            ja_hits.append(int(hit))
        precisions.append(_precision_at_k(candidates, gold, k=3))
        if not hit:
            undiscovered.append(
                {
                    "source_id": row.source_id,
                    "class": "undiscovered_unconfirmed_probe",
                    "split": row.split,
                    "family": row.family,
                }
            )
    fallback = None
    subscribe_ok = False
    try:
        from tempfile import TemporaryDirectory

        from app.database import Database

        xml = (fixture_root / "rss" / "g3_oracle_feed.xml").read_bytes()
        parsed = feedparser.parse(xml, resolve_relative_uris=False, sanitize_html=True)
        items = []
        for entry in parsed.entries:
            link = str(entry.get("link") or "")
            title = str(entry.get("title") or "")
            if link and title:
                items.append({"title": title, "link": link, "summary": str(entry.get("summary") or "")})
        preview = {"title": "fixture", "source_url": "https://blog.example.com/feed.xml", "items": items}
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            database = Database(Path(directory) / "g1-e2e.db")
            database.initialize()
            result = ingest_feed_events(database, preview=preview, retrieved_at="2026-08-01T00:00:00Z")
            subscribe_ok = bool(result.event_ids)
    except Exception:  # noqa: BLE001 - E2E failure is a measured miss
        subscribe_ok = False

    recall = hits / len(eligible_feed) if eligible_feed else 0.0
    precision_at_3 = sum(precisions) / len(precisions) if precisions else 0.0
    family_recall = {
        family: (sum(values) / len(values) if values else 0.0) for family, values in family_hits.items()
    }
    ja_recall = sum(ja_hits) / len(ja_hits) if ja_hits else 0.0
    failures = [
        "g1_production_confirm_unmeasured",
        "g1_live_path_unmeasured",
    ]
    if not subscribe_ok:
        failures.append("g1_subscribe_e2e")
    if recall < floors["g1_feed_recall"]:
        failures.append("g1_feed_recall")
    if ja_recall < floors["g1_japanese_recall"]:
        failures.append("g1_japanese_recall")
    if precision_at_3 < floors["g1_precision_at_3"]:
        failures.append("g1_precision_at_3")
    failures.append("g1_no_feed_fallback_unmeasured")
    for family, value in family_recall.items():
        if family != "no_rss_web" and value < floors["g1_family_recall"]:
            failures.append(f"g1_family_recall:{family}")
    return {
        "eligible_feed_count": len(eligible_feed),
        "probe_limit": len(well_known_feed_urls("https://example.com/")),
        "feed_recall_unconfirmed_probe": recall,
        "precision_at_3": precision_at_3,
        "japanese_recall": ja_recall,
        "family_recall": family_recall,
        "no_feed_fallback": fallback,
        "subscribe_e2e_fixture": subscribe_ok,
        "production_confirm_measured": False,
        "undiscovered": undiscovered,
        "passed": False,
        "failures": failures,
    }


def evaluate_g2(sources: list[G0Source], *, floors: dict[str, float]) -> dict[str, Any]:
    by_topic: dict[str, list[G0Source]] = defaultdict(list)
    for row in sources:
        if row.policy_status == "eligible" and row.relevance == "relevant":
            by_topic[row.topic_id].append(row)
    topic_rows = []
    weak_primary = []
    primary_hits = 0
    primary_total = 0
    relevant_hits = 0
    relevant_total = 0
    p20_hits = 0
    p20_pred = 0
    ja_hits = 0
    ja_total = 0
    blog_hits = 0
    blog_total = 0
    no_rss_hits = 0
    no_rss_total = 0
    blog_families = {"official_blog", "corp_tech_blog", "personal_dev_blog"}
    for topic, rows in sorted(by_topic.items()):
        result = discover_sources_for_topics(
            (topic,),
            SourceRegistry(),
            include_curated_seeds=True,
            persist_registry=False,
            limit=50,
        )
        predicted = [_canonical(item.canonical_url) for item in result.items]
        gold_urls = {_canonical(row.canonical_url) for row in rows}
        primary = {_canonical(row.canonical_url) for row in rows if row.authority == "primary"}
        top20 = set(predicted[:20])
        top50 = set(predicted[:50])
        topic_primary_recall = (len(primary & top20) / len(primary)) if primary else 0.0
        topic_relevant_recall = (len(gold_urls & top50) / len(gold_urls)) if gold_urls else 0.0
        topic_rows.append(
            {
                "topic_id": topic,
                "primary_recall_at_20": topic_primary_recall,
                "relevant_recall_at_50": topic_relevant_recall,
                "predicted_count": len(predicted),
                "predicted_urls": predicted,
                "predicted_provenance": [
                    {
                        "url": _canonical(item.canonical_url),
                        "family": item.family,
                        "discovery_provenance": item.discovery_provenance,
                        "authority_status": item.authority_status,
                        "verification_status": item.verification_status,
                    }
                    for item in result.items
                ],
            }
        )
        if primary and topic_primary_recall < floors["g2_min_topic_primary_recall"]:
            weak_primary.append(topic)
        primary_hits += len(primary & top20)
        primary_total += len(primary)
        relevant_hits += len(gold_urls & top50)
        relevant_total += len(gold_urls)
        p20_hits += len(set(predicted[:20]) & gold_urls)
        p20_pred += min(20, len(predicted)) if predicted else 0
        for row in rows:
            url = _canonical(row.canonical_url)
            if row.language == "ja":
                ja_total += 1
                ja_hits += int(url in top50)
            if row.family in blog_families:
                blog_total += 1
                blog_hits += int(url in top50)
            if row.family == "no_rss_web":
                no_rss_total += 1
                no_rss_hits += int(url in top50)
    metrics = {
        "primary_recall_at_20": primary_hits / primary_total if primary_total else 0.0,
        "relevant_recall_at_50": relevant_hits / relevant_total if relevant_total else 0.0,
        "precision_at_20": p20_hits / p20_pred if p20_pred else 0.0,
        "japanese_recall_at_50": ja_hits / ja_total if ja_total else 0.0,
        "blog_recall_at_50": blog_hits / blog_total if blog_total else 0.0,
        "no_rss_recall_at_50": no_rss_hits / no_rss_total if no_rss_total else 0.0,
        "weak_primary_topics": weak_primary,
        "gold_injected": False,
    }
    failures = ["g2_production_retrieval_below_floor"]
    if metrics["primary_recall_at_20"] < floors["g2_primary_recall_at_20"]:
        failures.append("g2_primary_recall_at_20")
    if metrics["relevant_recall_at_50"] < floors["g2_relevant_recall_at_50"]:
        failures.append("g2_relevant_recall_at_50")
    if metrics["precision_at_20"] < floors["g2_precision_at_20"]:
        failures.append("g2_precision_at_20")
    if metrics["japanese_recall_at_50"] < floors["g2_japanese_recall_at_50"]:
        failures.append("g2_japanese_recall_at_50")
    if metrics["blog_recall_at_50"] < floors["g2_blog_recall_at_50"]:
        failures.append("g2_blog_recall_at_50")
    if metrics["no_rss_recall_at_50"] < floors["g2_no_rss_recall_at_50"]:
        failures.append("g2_no_rss_recall_at_50")
    if weak_primary:
        failures.append("g2_weak_primary_topic")
    return {**metrics, "topics": topic_rows, "passed": False, "failures": failures}


def _fixture_field(item_xml: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(item_xml)
    if match is None:
        return ""
    return html.unescape(match.group(1)).strip()


def _oracle_entries(xml_bytes: bytes) -> list[dict[str, str]]:
    # This is deliberately a tiny parser for a repository-controlled RSS fixture.
    # Production/untrusted XML remains on the hardened ingestion path; keeping the
    # oracle independent from feedparser avoids comparing the parser with itself.
    text = xml_bytes.decode("utf-8")
    items = []
    for item_xml in _ITEM_RE.findall(text):
        title = _fixture_field(item_xml, _TITLE_RE)
        link = _fixture_field(item_xml, _LINK_RE)
        if title and link:
            items.append({"title": title, "link": link})
    return items


def evaluate_g3(sources: list[G0Source], *, floors: dict[str, float], fixtures: Path) -> dict[str, Any]:
    xml_path = fixtures / "rss" / "g3_oracle_feed.xml"
    xml_bytes = xml_path.read_bytes()
    oracle = _oracle_entries(xml_bytes)
    parsed = feedparser.parse(xml_bytes, resolve_relative_uris=False, sanitize_html=True)
    predicted = []
    for entry in parsed.entries:
        link = str(entry.get("link") or "")
        title = str(entry.get("title") or "")
        if link and title:
            predicted.append({"title": title.strip(), "link": link.strip()})
    oracle_links = [row["link"] for row in oracle]
    pred_links = [row["link"] for row in predicted]
    raw_recall = len(set(oracle_links) & set(pred_links)) / len(oracle_links) if oracle_links else 0.0
    important = [row["link"] for row in oracle if "important" in row["title"].lower()]
    important_recall = len(set(important) & set(pred_links)) / len(important) if important else 0.0
    dup_rate = (len(pred_links) - len(set(pred_links))) / len(pred_links) if pred_links else 0.0
    rss_subset = [row for row in sources if row.has_feed and row.policy_status == "eligible"]
    all_eligible = [row for row in sources if row.policy_status == "eligible"]
    rss_only_share = len(rss_subset) / len(all_eligible) if all_eligible else 0.0
    return {
        "fixture_raw_entry_recall": raw_recall,
        "fixture_important_update_recall": important_recall,
        "fixture_duplicate_item_rate": dup_rate,
        "catalog_rss_only_share": rss_only_share,
        "catalog_breadth_note": "catalog inclusion is not RSS oracle parity",
        "bulletfeed_universe_recall": None,
        "breadth_superiority_pp": None,
        "family_regression_measured": False,
        "live_oracle_unmeasured": True,
        "passed": False,
        "failures": [
            "g3_live_oracle_unmeasured",
            "g3_family_regression_unmeasured",
            "g3_breadth_not_acquisition",
        ],
        "floors": floors,
    }


def evaluate_g4(*, fixtures: Path, floors: dict[str, float]) -> dict[str, Any]:
    cases = [
        (
            "article_with_boilerplate.html",
            "https://blog.example.com/compiler-change",
            True,
            "unsafe transform",
        ),
        ("nav_only.html", "https://blog.example.com/nav", False, None),
    ]
    body_hits = 0
    boilerplate_fp = 0
    locator_ok = 0
    measured = 0
    for name, url, expect_body, needle in cases:
        path = fixtures / "rss" / name
        if not path.is_file():
            continue
        measured += 1
        robots = RobotsDecision(
            source_url=url,
            robots_url=None,
            allowed=True,
            reason="fixture",
            retrieved_at="2026-08-01T00:00:00Z",
        )
        enrichment = enrich_html_bytes(
            url=url,
            body=path.read_bytes(),
            robots=robots,
            retrieved_at="2026-08-01T00:00:00Z",
        )
        has_body = enrichment.reason == "enriched" and bool(enrichment.article_text)
        if expect_body and has_body and needle and needle in enrichment.article_text:
            body_hits += 1
        if "Site chrome" in enrichment.article_text:
            boilerplate_fp += 1
        if expect_body and enrichment.evidence_locator.startswith("dom:"):
            locator_ok += 1
    skip_fetch = not is_summary_only("x" * 400, feed_body="y" * 400)
    body_success = body_hits / measured if measured else 0.0
    failures = [
        "g4_sample_insufficient",
        "g4_update_detection_unmeasured",
        "g4_article_split_unmeasured",
    ]
    if measured < 10:
        failures.append("g4_n_lt_10")
    if body_success < floors["g4_body_success"]:
        failures.append("g4_body_success")
    if not skip_fetch:
        failures.append("g4_skip_sufficient_feed")
    return {
        "sample_count": measured,
        "body_success": body_success,
        "important_body_recall": body_success,
        "boilerplate_fp": boilerplate_fp / measured if measured else None,
        "article_split": None,
        "update_recall": None,
        "update_precision": None,
        "evidence_locator_ok": locator_ok,
        "sufficient_feed_skips_fetch": skip_fetch,
        "passed": False,
        "failures": failures,
        "floors": floors,
    }


def evaluate_g5(gold_dir: Path) -> dict[str, Any]:
    ssrf = evaluate_ssrf_suite(gold_dir / "ssrf_adversarial.json")
    discovery_never_evidence = source_candidate_allows_claim_evidence() is False
    identity = {
        "redirect_same_source_measured": False,
        "discovery_never_evidence": discovery_never_evidence,
        "robots_not_success_measured": False,
    }
    failures = list(ssrf.get("failures") or [])
    if not identity["redirect_same_source_measured"]:
        failures.append("g5_identity_unmeasured")
    if not identity["robots_not_success_measured"]:
        failures.append("g5_robots_unmeasured")
    if not discovery_never_evidence:
        failures.append("g5_discovery_evidence_leak")
    return {
        "ssrf": ssrf,
        "identity": identity,
        "passed": False,
        "failures": failures,
    }


def evaluate_c1_gates(gold_dir: Path | None = None) -> dict[str, Any]:
    directory = gold_dir or GOLD_C1
    sources = load_g0_sources(directory / "sources.json")
    floors = _load_floors(directory)
    g0 = evaluate_g0(directory)
    g1 = evaluate_g1(sources, floors=floors)
    g2 = evaluate_g2(sources, floors=floors)
    g3 = evaluate_g3(sources, floors=floors, fixtures=FIXTURES)
    g4 = evaluate_g4(fixtures=FIXTURES, floors=floors)
    g5 = evaluate_g5(directory)
    return {
        "report_version": "product-gap-c1-g1g5-v2",
        "g0": g0.as_dict(),
        "g1": g1,
        "g2": g2,
        "g3": g3,
        "g4": g4,
        "g5": g5,
        "passed": False,
    }
