from app.services.osv_source import normalize_osv_vulnerabilities


def test_normalize_osv_vulnerabilities_preserves_advisory_identity() -> None:
    vulnerabilities = [
        {
            "id": "GHSA-aaaa-bbbb-cccc",
            "published": "2026-08-20T00:00:00Z",
            "summary": "example advisory",
        }
    ]

    observations = normalize_osv_vulnerabilities(
        ecosystem="PyPI",
        package="requests",
        version="2.31.0",
        vulnerabilities=vulnerabilities,
    )

    assert len(observations) == 1
    observation = observations[0]
    assert observation.source_type == "osv"
    assert observation.source_key == "PyPI:requests@2.31.0"
    assert observation.source_observation_id == "GHSA-aaaa-bbbb-cccc"
    assert observation.original_url.endswith("/GHSA-aaaa-bbbb-cccc")
