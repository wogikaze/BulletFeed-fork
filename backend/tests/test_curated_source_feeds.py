from app.services.source_catalog import SourceKind
from app.services.source_discovery_seeds import (
    CURATED_SOURCE_SEEDS,
    CURATED_SUBSCRIPTION_FEED_SEEDS,
    DiscoveryProvenance,
    official_subscribe_seeds_for_topic,
)
from app.services.source_registry import canonicalize_url


def test_curated_feed_catalog_has_broad_official_coverage() -> None:
    all_seeds = (*CURATED_SOURCE_SEEDS, *CURATED_SUBSCRIPTION_FEED_SEEDS)
    feeds = [seed for seed in all_seeds if seed.family is SourceKind.RSS_ATOM]
    urls = [canonicalize_url(seed.url) for seed in feeds]

    assert len(feeds) >= 60
    assert len(urls) == len(set(urls))
    assert all(seed.provenance == DiscoveryProvenance.WEBSITE_FEED for seed in feeds)
    assert all(seed.url.startswith("https://") for seed in feeds)
    assert {
        canonicalize_url("https://go.dev/blog/feed.atom"),
        canonicalize_url("https://aws.amazon.com/about-aws/whats-new/recent/feed/"),
        canonicalize_url("https://kubernetes.io/docs/reference/issues-security/official-cve-feed/feed.xml"),
        canonicalize_url("https://huggingface.co/blog/feed.xml"),
    } <= set(urls)


def test_expanded_feeds_are_attached_to_matching_topics() -> None:
    go_urls = {
        canonicalize_url(seed.url)
        for seed in official_subscribe_seeds_for_topic("Go")
    }
    react_urls = {
        canonicalize_url(seed.url)
        for seed in official_subscribe_seeds_for_topic("React")
    }
    company_urls = {
        canonicalize_url(seed.url)
        for seed in official_subscribe_seeds_for_topic("Apple")
    }
    model_urls = {
        canonicalize_url(seed.url)
        for seed in official_subscribe_seeds_for_topic("Hugging Face")
    }

    assert canonicalize_url("https://go.dev/blog/feed.atom") in go_urls
    assert canonicalize_url("https://blog.jetbrains.com/go/feed/") in go_urls
    assert canonicalize_url("https://reactnative.dev/blog/rss.xml") in react_urls
    assert canonicalize_url("https://nextjs.org/feed.xml") in react_urls
    assert canonicalize_url("https://www.apple.com/newsroom/rss-feed.rss") in company_urls
    assert canonicalize_url("https://huggingface.co/blog/feed.xml") in model_urls


def test_curated_feed_seeds_preserve_source_explanation() -> None:
    all_seeds = (*CURATED_SOURCE_SEEDS, *CURATED_SUBSCRIPTION_FEED_SEEDS)
    feeds = [seed for seed in all_seeds if seed.family is SourceKind.RSS_ATOM]

    assert all(seed.publisher_slug and seed.publisher_name for seed in feeds)
    assert all(seed.homepage_url.startswith("https://") for seed in feeds)
    assert all(seed.concept_ids and seed.display_name and seed.why for seed in feeds)
