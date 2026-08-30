from app.services.impact_features import (
    IMPACT_FEATURE_VERSION,
    build_impact_record,
    parse_observation_payload,
    ranking_impact_snapshot,
)


def test_lossy_title_record_does_not_invent_critical_severity() -> None:
    record = build_impact_record(
        source_type="github_advisory",
        source_key="GHSA-demo",
        delta_type="new_fact",
        title="Advisory for example",
        summary="A package is affected.",
    )
    snapshot = ranking_impact_snapshot(record)
    assert snapshot["version"] == "impact-signals-v1"
    assert snapshot["signals"]["security_severity"]["value"] == "unknown"


def test_structured_payload_changes_security_severity() -> None:
    lossy = ranking_impact_snapshot(
        build_impact_record(
            source_type="github_advisory",
            source_key="GHSA-demo",
            delta_type="new_fact",
            title="Advisory for example",
            summary="A package is affected.",
        )
    )
    structured = ranking_impact_snapshot(
        build_impact_record(
            source_type="github_advisory",
            source_key="GHSA-demo",
            delta_type="new_fact",
            title="Advisory for example",
            summary="A package is affected.",
            payload={
                "severity": "critical",
                "cvss": {"vector_string": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"},
                "affected": [{"package": {"name": "example"}}],
            },
            claim_value="affected",
            claim_detail="example 1.0.0 is affected",
        )
    )
    assert lossy["signals"]["security_severity"]["value"] == "unknown"
    assert structured["signals"]["security_severity"]["value"] == "critical"
    assert structured["signals"]["security_severity"]["source_field"] == "payload.severity"
    assert structured["signals"]["affected_packages"]["value"]


def test_invalid_payload_json_is_empty_object() -> None:
    assert parse_observation_payload("{") == {}
    assert parse_observation_payload('["not-an-object"]') == {}
    record = build_impact_record(
        source_type="statuspage",
        source_key="acme",
        delta_type="new_fact",
        title="Latency",
        summary="Investigating",
        payload=parse_observation_payload("{"),
    )
    assert record["impact_feature_version"] == IMPACT_FEATURE_VERSION
    assert "payload" not in record
