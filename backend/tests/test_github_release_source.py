from app.services.github_release_source import normalize_github_releases


def test_normalize_github_releases_keeps_canonical_identity_and_payload() -> None:
    releases = [
        {
            "id": 42,
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/acme/widget/releases/tag/v2.0.0",
            "published_at": "2026-08-20T12:00:00Z",
            "body": "breaking change",
        }
    ]

    observations = normalize_github_releases("acme", "widget", releases)

    assert len(observations) == 1
    observation = observations[0]
    assert observation.source_type == "github_release"
    assert observation.source_key == "acme/widget"
    assert observation.source_observation_id == "release:42"
    assert observation.original_url.endswith("/releases/tag/v2.0.0")
    assert observation.payload["tag_name"] == "v2.0.0"
