"""Japanese technical feeds that can be recommended from existing concepts.

This module is data-only. Network access stays in the existing RSS fetcher and
source discovery remains a recommendation step rather than Claim evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

JapaneseAuthorityClass = Literal["community", "secondary"]
INDEX_DERIVED_SLUG_PREFIX = "idx-"


@dataclass(frozen=True)
class JapaneseFeedSpec:
    publisher_slug: str
    publisher_name: str
    homepage_url: str
    url: str
    concept_ids: tuple[str, ...]
    display_name: str
    why: str
    authority_class: JapaneseAuthorityClass


# Community platforms and broad indexes are useful discovery surfaces but must
# never inherit the RSS family's historical "authoritative" default merely
# because they speak Atom/RSS. Broad-index entries link onward to original
# publishers; the index host itself is not publisher authority.
_COMMUNITY_HOSTS = frozenset(
    {
        "b.hatena.ne.jp",
        "qiita.com",
        "yamadashy.github.io",
        "zenn.dev",
    }
)
_SECONDARY_HOSTS = frozenset(
    {
        "developers.freee.co.jp",
        "engineering.dena.com",
        "engineering.mercari.com",
        "techblog.lycorp.co.jp",
        "techblog.zozo.com",
    }
)

# Keep tags explicit instead of mechanically turning every ontology concept
# into a URL. This prevents invalid or overly broad community-feed candidates.
_PLATFORM_TAGS: dict[str, str] = {
    "android": "android",
    "go": "go",
    "kotlin": "kotlin",
    "python": "python",
    "react": "react",
    "ruby": "ruby",
    "rust": "rust",
    "security": "security",
    "oss_security": "security",
    "typescript": "typescript",
    "webassembly": "webassembly",
}

# Broad Japanese discovery feeds are intentionally topic-wide. They replace
# "keep hand-adding companies" as the coverage mechanism: Hatena discovers a
# wide Japanese IT web surface, while tech-blog-rss-feed aggregates articles
# from a large, independently maintained set of Japanese company tech blogs.
_BROAD_TECH_CONCEPTS = tuple(
    sorted(
        set(_PLATFORM_TAGS)
        | {
            "ai",
            "backend",
            "cloud",
            "compiler",
            "database",
            "devops",
            "linux",
            "llm",
            "machine_learning",
            "server",
            "web",
        }
    )
)
_BROAD_DISCOVERY_FEEDS: tuple[JapaneseFeedSpec, ...] = (
    JapaneseFeedSpec(
        publisher_slug="hatena-bookmark-it-new",
        publisher_name="はてなブックマーク テクノロジー新着",
        homepage_url="https://b.hatena.ne.jp/entrylist/it",
        url="https://b.hatena.ne.jp/entrylist/it.rss",
        concept_ids=_BROAD_TECH_CONCEPTS,
        display_name="はてなブックマーク テクノロジー新着",
        why="Broad Japanese IT discovery feed; entry links point to original publishers",
        authority_class="community",
    ),
    JapaneseFeedSpec(
        publisher_slug="hatena-bookmark-it-hot",
        publisher_name="はてなブックマーク テクノロジー人気",
        homepage_url="https://b.hatena.ne.jp/hotentry/it",
        url="https://b.hatena.ne.jp/hotentry/it.rss",
        concept_ids=_BROAD_TECH_CONCEPTS,
        display_name="はてなブックマーク テクノロジー人気",
        why="Broad Japanese IT popularity feed; entry links point to original publishers",
        authority_class="community",
    ),
    JapaneseFeedSpec(
        publisher_slug="tech-blog-rss-feed",
        publisher_name="企業テックブログRSS",
        homepage_url="https://yamadashy.github.io/tech-blog-rss-feed/",
        url="https://yamadashy.github.io/tech-blog-rss-feed/feeds/rss.xml",
        concept_ids=_BROAD_TECH_CONCEPTS,
        display_name="企業テックブログRSS",
        why="Broad Japanese company-tech-blog aggregate; entry links point to original publishers",
        authority_class="community",
    ),
)

# Keep a small set of known direct feeds as regression/fallback coverage. Product
# coverage must not depend on this list; the broad feeds above are the expansion
# mechanism.
_ENGINEERING_BLOGS: tuple[JapaneseFeedSpec, ...] = (
    JapaneseFeedSpec(
        publisher_slug="lycorp-tech",
        publisher_name="LINEヤフー Tech Blog",
        homepage_url="https://techblog.lycorp.co.jp/ja",
        url="https://techblog.lycorp.co.jp/ja/feed/index.xml",
        concept_ids=("android", "go", "kotlin", "react", "security", "typescript"),
        display_name="LINEヤフー Tech Blog",
        why="Japanese first-party engineering blog feed",
        authority_class="secondary",
    ),
    JapaneseFeedSpec(
        publisher_slug="mercari-engineering",
        publisher_name="Mercari Engineering",
        homepage_url="https://engineering.mercari.com/blog/",
        url="https://engineering.mercari.com/blog/feed.xml",
        concept_ids=("android", "go", "kotlin", "react", "security", "typescript"),
        display_name="Mercari Engineering",
        why="Japanese first-party engineering blog feed",
        authority_class="secondary",
    ),
    JapaneseFeedSpec(
        publisher_slug="freee-developers",
        publisher_name="freee Developers Hub",
        homepage_url="https://developers.freee.co.jp",
        url="https://developers.freee.co.jp/feed",
        concept_ids=("go", "react", "ruby", "security", "typescript"),
        display_name="freee Developers Hub",
        why="Japanese first-party engineering blog feed",
        authority_class="secondary",
    ),
    JapaneseFeedSpec(
        publisher_slug="dena-engineering",
        publisher_name="DeNA Engineering",
        homepage_url="https://engineering.dena.com/blog/",
        url="https://engineering.dena.com/blog/index.xml",
        concept_ids=("android", "go", "kotlin", "python", "react"),
        display_name="DeNA Engineering",
        why="Japanese first-party engineering blog feed",
        authority_class="secondary",
    ),
    JapaneseFeedSpec(
        publisher_slug="zozo-tech",
        publisher_name="ZOZO TECH BLOG",
        homepage_url="https://techblog.zozo.com",
        url="https://techblog.zozo.com/feed",
        concept_ids=("android", "go", "kotlin", "python", "react", "typescript"),
        display_name="ZOZO TECH BLOG",
        why="Japanese first-party engineering blog feed",
        authority_class="secondary",
    ),
)


def japanese_feed_specs(active_concept_ids: set[str]) -> tuple[JapaneseFeedSpec, ...]:
    """Return deterministic Japanese feed candidates for active concepts."""
    specs: list[JapaneseFeedSpec] = []
    seen: set[str] = set()
    for concept_id in sorted(active_concept_ids):
        tag = _PLATFORM_TAGS.get(concept_id)
        if tag is None:
            continue
        for spec in (
            JapaneseFeedSpec(
                publisher_slug="zenn-community",
                publisher_name="Zenn",
                homepage_url="https://zenn.dev",
                url=f"https://zenn.dev/topics/{tag}/feed",
                concept_ids=(concept_id,),
                display_name=f"Zenn {tag} topic feed",
                why=f"Japanese Zenn articles tagged {tag}",
                authority_class="community",
            ),
            JapaneseFeedSpec(
                publisher_slug="qiita-community",
                publisher_name="Qiita",
                homepage_url="https://qiita.com",
                url=f"https://qiita.com/tags/{tag}/feed.atom",
                concept_ids=(concept_id,),
                display_name=f"Qiita {tag} tag feed",
                why=f"Japanese Qiita articles tagged {tag}",
                authority_class="community",
            ),
        ):
            if spec.url not in seen:
                seen.add(spec.url)
                specs.append(spec)

    for group in (_BROAD_DISCOVERY_FEEDS, _ENGINEERING_BLOGS):
        for spec in group:
            if active_concept_ids.isdisjoint(spec.concept_ids) or spec.url in seen:
                continue
            seen.add(spec.url)
            specs.append(spec)
    return tuple(specs)


def japanese_feed_authority_class(url: str) -> JapaneseAuthorityClass | None:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host in _COMMUNITY_HOSTS:
        return "community"
    if host in _SECONDARY_HOSTS:
        return "secondary"
    return None


def japanese_index_feed_urls() -> frozenset[str]:
    """Aggregate feeds whose entries point at original publishers."""
    return frozenset(spec.url for spec in _BROAD_DISCOVERY_FEEDS)


def japanese_broad_tech_concepts() -> tuple[str, ...]:
    return _BROAD_TECH_CONCEPTS


def japanese_feed_hosts() -> tuple[str, ...]:
    """Hosts verified as feed endpoints and suitable for an explicit RSS allowlist."""
    return tuple(sorted(_COMMUNITY_HOSTS | _SECONDARY_HOSTS))
