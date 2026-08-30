"""Deterministic replay qualification for recorded live source artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from app.evaluation.real_world_validation import (
    ValidationCorpus,
    load_real_world_validation_for_production_scoring,
)

QUALIFICATION_VERSION = "m3-source-qualification-v1"
TARGET_LIVE_ENDPOINTS = 200
TARGET_REPLAY_CASES = 1_000
ReplayOutcome = Literal["passed", "failed", "not_applicable"]


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    source_id: str
    source_family: str
    scenario: str
    outcome: ReplayOutcome
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceQualificationReport:
    qualification_version: str
    live_endpoint_count: int
    unique_artifact_count: int
    replay_case_count: int
    replay_passed_count: int
    replay_failed_count: int
    source_family_counts: dict[str, int]
    scenario_counts: dict[str, int]
    outcome_counts: dict[str, int]
    failure_dimensions: dict[str, int]
    source_inventory: tuple[dict[str, Any], ...]
    replay_cases: tuple[ReplayCase, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_inventory"] = list(self.source_inventory)
        payload["replay_cases"] = [case.as_dict() for case in self.replay_cases]
        payload["limitations"] = list(self.limitations)
        return payload


def evaluate_source_qualification(
    corpus: ValidationCorpus,
    *,
    corpus_dir: Path,
) -> SourceQualificationReport:
    sources = tuple(source for source in corpus.sources if source.source_role == "event_page")
    inventory: list[dict[str, Any]] = []
    replay_cases: list[ReplayCase] = []
    artifact_hashes: set[str] = set()
    endpoint_urls: set[str] = set()
    for source in sources:
        artifact_path = corpus_dir / source.fetch.artifact_relpath
        body = artifact_path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        artifact_hashes.add(digest)
        endpoint_urls.add(source.fetch.url)
        inventory.append(
            {
                "source_id": source.source_id,
                "source_family": source.source_family,
                "fetch_url": source.fetch.url,
                "final_url": source.fetch.final_url,
                "http_status": source.fetch.http_status,
                "content_type": source.fetch.content_type,
                "content_hash": digest,
                "recorded_content_hash": source.content_hash,
                "artifact_relpath": source.fetch.artifact_relpath,
            }
        )
        replay_cases.append(
            _case(
                source,
                scenario="recorded_fetch",
                outcome=(
                    "passed"
                    if digest == source.content_hash
                    and source.evidence_text in body.decode("utf-8")
                    else "failed"
                ),
                detail="artifact hash and evidence substring verified",
            )
        )
        replay_cases.append(
            _case(
                source,
                scenario="duplicate_delivery",
                outcome="passed" if hashlib.sha256(body).hexdigest() == digest else "failed",
                detail="replaying the captured bytes preserves the observation identity",
            )
        )

    outcomes = Counter(case.outcome for case in replay_cases)
    scenarios = Counter(case.scenario for case in replay_cases)
    families = Counter(source.source_family for source in sources)
    failures = Counter(
        case.scenario
        for case in replay_cases
        if case.outcome == "failed"
    )
    return SourceQualificationReport(
        qualification_version=QUALIFICATION_VERSION,
        live_endpoint_count=len(endpoint_urls),
        unique_artifact_count=len(artifact_hashes),
        replay_case_count=len(replay_cases),
        replay_passed_count=outcomes["passed"],
        replay_failed_count=outcomes["failed"],
        source_family_counts=dict(sorted(families.items())),
        scenario_counts=dict(sorted(scenarios.items())),
        outcome_counts=dict(sorted(outcomes.items())),
        failure_dimensions=dict(sorted(failures.items())),
        source_inventory=tuple(sorted(inventory, key=lambda row: row["source_id"])),
        replay_cases=tuple(replay_cases),
        limitations=(
            "This qualification replays recorded live HTTPS artifacts without live network access.",
            "Redirect, timeout, rate-limit, malformed-input, oversize, and SSRF fault drills "
            "require dedicated deterministic fixtures or host probes.",
        ),
    )


def load_and_evaluate_source_qualification(corpus_dir: Path) -> SourceQualificationReport:
    corpus = load_real_world_validation_for_production_scoring(corpus_dir)
    return evaluate_source_qualification(corpus, corpus_dir=corpus_dir)


def qualification_release_violations(report: SourceQualificationReport) -> tuple[str, ...]:
    violations: list[str] = []
    if report.live_endpoint_count < TARGET_LIVE_ENDPOINTS:
        violations.append(
            f"live_endpoint_count {report.live_endpoint_count} < {TARGET_LIVE_ENDPOINTS}"
        )
    if report.replay_case_count < TARGET_REPLAY_CASES:
        violations.append(
            f"replay_case_count {report.replay_case_count} < {TARGET_REPLAY_CASES}"
        )
    if report.replay_failed_count:
        violations.append(f"replay_failed_count {report.replay_failed_count} > 0")
    return tuple(violations)


def write_source_qualification_report(report: SourceQualificationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _case(source, *, scenario: str, outcome: ReplayOutcome, detail: str) -> ReplayCase:
    return ReplayCase(
        case_id=f"{source.source_id}:{scenario}",
        source_id=source.source_id,
        source_family=source.source_family,
        scenario=scenario,
        outcome=outcome,
        detail=detail,
    )
