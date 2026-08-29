from __future__ import annotations

import inspect
import json
from pathlib import Path

from app.services.impact_signals import (
    IMPACT_SIGNAL_VERSION,
    SIGNAL_NAMES,
    UNKNOWN,
    extract_impact_signals,
    features_for_ranking,
    snapshot_impact_signals,
)
from app.services.ranking import evaluate_importance

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "impact_signals"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _unknown_names(signals) -> set[str]:
    return {name for name in SIGNAL_NAMES if getattr(signals, name).value == UNKNOWN}


def test_version_string_is_present_and_stable() -> None:
    signals = extract_impact_signals(_load_fixture("generic_publication.json"))

    assert IMPACT_SIGNAL_VERSION == "impact-signals-v1"
    assert signals.version == IMPACT_SIGNAL_VERSION
    snapshot = snapshot_impact_signals(_load_fixture("generic_publication.json"))
    assert snapshot["version"] == IMPACT_SIGNAL_VERSION


def test_empty_advisory_severity_stays_unknown_not_critical() -> None:
    empty = extract_impact_signals(_load_fixture("security_empty_severity.json"))
    missing = extract_impact_signals({"source_type": "github_advisory"})

    assert empty.security_severity.value == UNKNOWN
    assert missing.security_severity.value == UNKNOWN
    assert empty.security_severity.value != "critical"
    assert empty.security_severity.confidence != "high"
    assert missing.security_severity.confidence != "high"


def test_security_critical_vs_low_are_distinguished() -> None:
    critical = extract_impact_signals(_load_fixture("security_critical.json"))
    low = extract_impact_signals(_load_fixture("security_low.json"))

    assert critical.security_severity.value == "critical"
    assert low.security_severity.value == "low"
    assert critical.security_severity.source_field == "severity"
    assert critical.security_exploitability.value == "high"
    assert low.security_exploitability.value == "low"
    assert critical.affected_packages.value["packages"] == [{"ecosystem": "pip", "name": "demo"}]


def test_version_significance_major_vs_patch() -> None:
    major = extract_impact_signals(_load_fixture("release_major.json"))
    patch = extract_impact_signals(_load_fixture("release_patch.json"))

    assert major.version_significance.value == "major"
    assert patch.version_significance.value == "patch"
    assert major.version_significance.source_field == "tag_name"
    assert patch.version_significance.source_field == "tag_name"


def test_statuspage_critical_major_vs_none() -> None:
    critical = extract_impact_signals(_load_fixture("incident_critical.json"))
    major = extract_impact_signals(_load_fixture("incident_major.json"))
    none = extract_impact_signals(_load_fixture("incident_none.json"))

    assert critical.incident_impact.value == "critical"
    assert major.incident_impact.value == "major"
    assert none.incident_impact.value == "none"
    assert none.incident_impact.value != UNKNOWN
    assert critical.incident_status.value == "investigating"
    assert critical.incident_recovery.value == "unresolved"
    assert none.incident_recovery.value == "recovered"


def test_correction_from_structured_delta_type_or_explicit_flag() -> None:
    structured = extract_impact_signals(_load_fixture("correction.json"))
    delta_only = extract_impact_signals({"source_type": "rss_atom", "delta_type": "correction"})
    conflict = extract_impact_signals(
        {"source_type": "github_release", "delta_type": "unresolved_contradiction"}
    )
    explicit = extract_impact_signals({"source_type": "statuspage", "explicit_correction": True})

    assert structured.correction_or_conflict.value == "correction"
    assert structured.correction_or_conflict.source_field == "delta_type"
    assert structured.correction_or_conflict.confidence == "high"
    assert delta_only.correction_or_conflict.value == "correction"
    assert conflict.correction_or_conflict.value == "conflict"
    assert explicit.correction_or_conflict.value == "correction"


def test_deprecation_and_breaking_from_structured_flags_or_markers() -> None:
    structured = extract_impact_signals(_load_fixture("deprecation.json"))
    breaking_flag = extract_impact_signals(
        {"source_type": "github_release", "tag_name": "v2.0.0", "breaking": True}
    )
    inferred = extract_impact_signals(
        {
            "source_type": "json_feed",
            "title": "Upcoming deprecation of Checkout API",
        }
    )
    breaking_body = extract_impact_signals(
        {
            "source_type": "github_release",
            "tag_name": "v3.0.0",
            "body": "## Breaking Changes\nThe v1 client is unsupported.",
        }
    )

    assert structured.breaking_deprecation_removal.value == "deprecation"
    assert structured.breaking_deprecation_removal.confidence == "high"
    assert structured.breaking_deprecation_removal.source_field in {"deprecated", "lifecycle_state"}
    assert breaking_flag.breaking_deprecation_removal.value == "breaking"
    assert inferred.breaking_deprecation_removal.value == "deprecation"
    assert inferred.breaking_deprecation_removal.source_field.startswith("inferred:")
    assert inferred.breaking_deprecation_removal.confidence == "low"
    assert "Inferred" in inferred.breaking_deprecation_removal.reason
    assert breaking_body.breaking_deprecation_removal.value == "breaking"
    assert breaking_body.breaking_deprecation_removal.source_field.startswith("inferred:")


def test_generic_publication_stays_mostly_unknown() -> None:
    signals = extract_impact_signals(_load_fixture("generic_publication.json"))
    unknown = _unknown_names(signals)

    assert unknown == set(SIGNAL_NAMES)
    assert all(getattr(signals, name).value != "high" for name in SIGNAL_NAMES)
    assert all(getattr(signals, name).confidence != "high" for name in SIGNAL_NAMES)


def test_policy_uses_structured_deadline_and_audience_only() -> None:
    signals = extract_impact_signals(_load_fixture("policy.json"))

    assert signals.deadline.value == "2026-10-01"
    assert signals.deadline.source_field == "effective_date"
    assert signals.scope_audience.value == "all_tenants"
    assert signals.security_severity.value == UNKNOWN
    assert signals.incident_impact.value == UNKNOWN
    assert signals.version_significance.value == UNKNOWN
    assert signals.correction_or_conflict.value == UNKNOWN


def test_snapshot_is_json_serializable_and_stable() -> None:
    record = _load_fixture("security_critical.json")
    first = extract_impact_signals(record).to_snapshot()
    second = snapshot_impact_signals(record)

    assert first == second
    encoded = json.dumps(first, sort_keys=True)
    assert json.loads(encoded) == first
    assert extract_impact_signals(record).to_json() == extract_impact_signals(record).to_json()
    ranking_features = features_for_ranking(extract_impact_signals(record))
    assert ranking_features == first
    assert set(first["signals"]) == set(SIGNAL_NAMES)
    for name, signal in first["signals"].items():
        assert set(signal) == {"value", "source_field", "reason", "confidence"}, name


def test_extractor_signature_does_not_accept_relation_or_novelty() -> None:
    parameters = inspect.signature(extract_impact_signals).parameters

    assert "relation_level" not in parameters
    assert "novelty" not in parameters
    assert list(parameters) == ["record"]


def test_relation_and_novelty_on_record_do_not_change_signals() -> None:
    base = _load_fixture("generic_publication.json")
    polluted = {
        **base,
        "relation_level": "direct",
        "novelty": "high",
        "personalization_rank": 1000,
        "matched_topics": ["security"],
    }

    assert extract_impact_signals(base).to_snapshot() == extract_impact_signals(polluted).to_snapshot()
    assert extract_impact_signals(polluted).scope_audience.value == UNKNOWN
    assert extract_impact_signals(polluted).security_severity.value == UNKNOWN


def test_each_signal_is_explainable() -> None:
    signals = extract_impact_signals(_load_fixture("security_critical.json"))

    for name in SIGNAL_NAMES:
        signal = getattr(signals, name)
        assert isinstance(signal.reason, str) and signal.reason
        assert signal.confidence in {"high", "medium", "low"}
        if signal.value == UNKNOWN:
            assert signal.confidence != "high"
            assert signal.source_field == ""
        else:
            assert signal.source_field


def test_evaluate_importance_scoring_is_unchanged() -> None:
    security = evaluate_importance(source_type="osv", delta_type="new_fact")
    correction = evaluate_importance(source_type="rss_atom", delta_type="correction")
    release = evaluate_importance(source_type="github_release", delta_type="detail")

    assert security.level == "high"
    assert correction.level == "high"
    assert release.level == "medium"


def test_fixtures_cover_required_source_families() -> None:
    families = {
        "security": _load_fixture("security_critical.json")["source_type"],
        "release": _load_fixture("release_major.json")["source_type"],
        "incident": _load_fixture("incident_critical.json")["source_type"],
        "deprecation": _load_fixture("deprecation.json")["source_type"],
        "policy": _load_fixture("policy.json")["source_type"],
        "generic": _load_fixture("generic_publication.json")["source_type"],
    }

    assert families["security"] == "github_advisory"
    assert families["release"] == "github_release"
    assert families["incident"] == "statuspage"
    assert families["deprecation"] == "json_feed"
    assert families["policy"] == "rss_atom"
    assert families["generic"] == "rss_atom"


def test_nested_payload_fields_are_read_as_structured_source() -> None:
    signals = extract_impact_signals(
        {
            "source_type": "github_advisory",
            "payload": {
                "severity": "high",
                "cvss": {
                    "score": 7.5,
                    "vector_string": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
                },
            },
        }
    )

    assert signals.security_severity.value == "high"
    assert signals.security_severity.source_field == "payload.severity"
    assert signals.security_exploitability.source_field == "payload.cvss.vector_string"
