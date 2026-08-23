from app.services.hacker_news_source import normalize_hacker_news_candidates


def test_hacker_news_candidates_are_discovery_observations() -> None:
    observations = normalize_hacker_news_candidates(
        [
            {
                "id": 123,
                "title": "Vendor ships release",
                "url": "https://vendor.example/releases/2",
                "time": 1787300000,
            }
        ]
    )

    assert len(observations) == 1
    observation = observations[0]
    assert observation.source_type == "hacker_news_discovery"
    assert observation.source_observation_id == "123"
    assert observation.original_url == "https://vendor.example/releases/2"
    assert observation.payload["title"] == "Vendor ships release"
