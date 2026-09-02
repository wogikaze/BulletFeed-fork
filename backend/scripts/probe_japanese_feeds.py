"""Probe Japanese feeds through the production RSS fetch/parser path.

This is intentionally not part of ordinary CI because it depends on live
third-party networks. It is safe to run manually and emits machine-readable
JSON for #315/#328 evidence.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from app.config import Settings
from app.services.index_publisher_discovery import original_article_hosts
from app.services.japanese_source_catalog import japanese_feed_hosts, japanese_index_feed_urls
from app.services.rss import preview_feed


@dataclass(frozen=True)
class ProbeTarget:
    source: str
    url: str
    source_class: str


TARGETS: tuple[ProbeTarget, ...] = (
    ProbeTarget("Zenn trend", "https://zenn.dev/feed", "community"),
    ProbeTarget("Zenn Rust", "https://zenn.dev/topics/rust/feed", "community"),
    ProbeTarget("Qiita Rust", "https://qiita.com/tags/rust/feed.atom", "community"),
    ProbeTarget(
        "はてなブックマーク テクノロジー新着",
        "https://b.hatena.ne.jp/entrylist/it.rss",
        "broad_index",
    ),
    ProbeTarget(
        "はてなブックマーク テクノロジー人気",
        "https://b.hatena.ne.jp/hotentry/it.rss",
        "broad_index",
    ),
    ProbeTarget(
        "企業テックブログRSS",
        "https://yamadashy.github.io/tech-blog-rss-feed/feeds/rss.xml",
        "broad_index",
    ),
    ProbeTarget(
        "LINEヤフー Tech Blog",
        "https://techblog.lycorp.co.jp/ja/feed/index.xml",
        "secondary",
    ),
    ProbeTarget(
        "Mercari Engineering",
        "https://engineering.mercari.com/blog/feed.xml",
        "secondary",
    ),
    ProbeTarget("freee Developers Hub", "https://developers.freee.co.jp/feed", "secondary"),
    ProbeTarget("DeNA Engineering", "https://engineering.dena.com/blog/index.xml", "secondary"),
    ProbeTarget("ZOZO TECH BLOG", "https://techblog.zozo.com/feed", "secondary"),
)


def _linked_hosts(items: list[dict[str, object]]) -> list[str]:
    hosts: set[str] = set()
    for item in items:
        raw = item.get("url") or item.get("link")
        if not isinstance(raw, str):
            continue
        host = (urlparse(raw).hostname or "").lower().rstrip(".")
        if host:
            hosts.add(host)
    return sorted(hosts)


async def _probe(target: ProbeTarget, settings: Settings) -> dict[str, object]:
    try:
        preview = await preview_feed(settings, target.url)
    except Exception as exc:
        return {
            **asdict(target),
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    items = preview.get("items") or []
    linked_hosts = _linked_hosts(items)
    publisher_hosts = (
        list(original_article_hosts(items, index_url=target.url))
        if target.url in japanese_index_feed_urls()
        else []
    )
    return {
        **asdict(target),
        "ok": bool(items),
        "resolved_url": preview.get("source_url"),
        "feed_title": preview.get("title"),
        "item_count": len(items),
        "linked_host_count": len(linked_hosts),
        "sample_linked_hosts": linked_hosts[:10],
        "publisher_host_count": len(publisher_hosts),
        "sample_publisher_hosts": publisher_hosts[:10],
        "sample_titles": [item.get("title") for item in items[:3]],
    }


async def main() -> int:
    settings = Settings(
        rss_allowed_hosts=",".join(japanese_feed_hosts()),
        request_timeout_seconds=10.0,
    )
    results = [await _probe(target, settings) for target in TARGETS]
    output = {
        "probe": "japanese-feed-production-preview-v2",
        "transport": "app.services.rss.preview_feed",
        "allowed_hosts": list(japanese_feed_hosts()),
        "results": results,
        "passed": sum(1 for item in results if item["ok"]),
        "attempted": len(results),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
