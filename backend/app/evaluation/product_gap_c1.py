"""Challenge-1 G0 corpus load and floor checks. Blind labels are not scored here."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DATASET_VERSION = "product-gap-c1-g0-v1"
MAJOR_FAMILIES = (
    "official_blog",
    "corp_tech_blog",
    "personal_dev_blog",
    "docs_changelog",
    "rss_atom_json",
    "no_rss_web",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class G0Source(_Strict):
    source_id: str = Field(min_length=1)
    site_url: str = Field(min_length=1)
    feed_url: str | None = None
    canonical_url: str = Field(min_length=1)
    topic_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    language: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    has_feed: bool
    domain: str = Field(min_length=1)
    registrable_domain: str = Field(min_length=1)
    policy_status: str = Field(min_length=1)
    relevance: str = Field(min_length=1)
    curation: str = Field(min_length=1)
    split: str = Field(min_length=1)


@dataclass(frozen=True)
class G0Report:
    dataset_version: str
    source_count: int
    topic_count: int
    families: dict[str, int]
    japanese_count: int
    no_rss_web_count: int
    blind_source_ratio: float
    unique_domains: int
    policy_blocked_count: int
    attested: bool
    floors_pass: bool
    failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version,
            "source_count": self.source_count,
            "topic_count": self.topic_count,
            "families": self.families,
            "japanese_count": self.japanese_count,
            "no_rss_web_count": self.no_rss_web_count,
            "blind_source_ratio": self.blind_source_ratio,
            "unique_domains": self.unique_domains,
            "policy_blocked_count": self.policy_blocked_count,
            "attested": self.attested,
            "floors_pass": self.floors_pass,
            "failures": list(self.failures),
        }


def load_g0_sources(path: Path) -> list[G0Source]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("G0 sources.json must be a list")
    return [G0Source.model_validate(item) for item in payload]


def load_attestation(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_g0(gold_dir: Path) -> G0Report:
    sources = load_g0_sources(gold_dir / "sources.json")
    attestation = load_attestation(gold_dir / "attestation.json")
    freeze = json.loads((gold_dir / "g0_freeze.json").read_text(encoding="utf-8"))
    sources_path = gold_dir / "sources.json"
    eligible = [row for row in sources if row.policy_status == "eligible" and row.relevance == "relevant"]
    families = Counter(row.family for row in eligible)
    for row in eligible:
        if row.has_feed:
            families["rss_atom_json"] += 1
    topics = {row.topic_id for row in eligible}
    japanese = sum(1 for row in eligible if row.language == "ja")
    no_rss = sum(1 for row in eligible if row.family == "no_rss_web")
    blind = sum(1 for row in sources if row.split == "blind")
    ratio = blind / len(sources) if sources else 0.0
    attested = attestation.get("status") == "attested" and bool(attestation.get("attested_by"))
    policy_blocked = sum(1 for row in sources if row.policy_status == "policy_blocked")
    floors = freeze["floors"]
    failures: list[str] = []
    expected_sources_hash = freeze.get("sources_sha256")
    actual_sources_hash = hashlib.sha256(sources_path.read_bytes()).hexdigest()
    if expected_sources_hash != actual_sources_hash:
        failures.append("sources_hash_mismatch")
    if len(eligible) < floors["min_sources"]:
        failures.append("min_sources")
    if len(topics) < floors["min_topics"]:
        failures.append("min_topics")
    if japanese < floors["min_japanese"]:
        failures.append("min_japanese")
    if no_rss < floors["min_no_rss_web"]:
        failures.append("min_no_rss_web")
    if ratio < floors["min_blind_ratio"]:
        failures.append("min_blind_ratio")
    for family in ("official_blog", "corp_tech_blog", "personal_dev_blog", "docs_changelog", "rss_atom_json"):
        if families.get(family, 0) < floors["min_per_major_family"]:
            failures.append(f"family:{family}")
    if policy_blocked < 1:
        failures.append("policy_blocked_absent")
    if not attested:
        failures.append("attestation_pending")
    return G0Report(
        dataset_version=str(freeze["dataset_version"]),
        source_count=len(eligible),
        topic_count=len(topics),
        families=dict(sorted(families.items())),
        japanese_count=japanese,
        no_rss_web_count=no_rss,
        blind_source_ratio=ratio,
        unique_domains=len({row.registrable_domain for row in sources}),
        policy_blocked_count=policy_blocked,
        attested=attested,
        floors_pass=not failures,
        failures=tuple(failures),
    )
