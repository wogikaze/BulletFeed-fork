from app.services.github_sbom_source import normalize_github_sbom


def test_normalize_github_sbom_keeps_repository_snapshot_identity() -> None:
    data = {
        "sbom": {
            "spdxVersion": "SPDX-2.3",
            "packages": [{"name": "requests", "externalRefs": []}],
        }
    }

    observation = normalize_github_sbom("acme", "widget", data)

    assert observation.source_type == "github_sbom"
    assert observation.source_key == "acme/widget"
    assert observation.source_observation_id == "sbom"
    assert observation.original_url == "https://github.com/acme/widget"
    assert observation.payload["sbom"]["spdxVersion"] == "SPDX-2.3"
