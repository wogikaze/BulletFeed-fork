"""Probe Japanese feeds through the production RSS fetch/parser path.

This is intentionally not part of ordinary CI because it depends on live
third-party networks. It is safe to run manually and emits machine-readable
JSON for #315/#328 evidence.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass

from app.config import Settings
from app.services.japanese_source_catalog import japanese_feed_hosts
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
    return {
        **asdict(target),
        "ok": bool(items),
        "resolved_url": preview.get("source_url"),
        "feed_title": preview.get("title"),
        "item_count": len(items),
        "sample_titles": [item.get("title") for item in items[:3]],
    }


async def main() -> int:
    settings = Settings(
        rss_allowed_hosts=",".join(japanese_feed_hosts()),
        request_timeout_seconds=10.0,
    )
    results = [await _probe(target, settings) for target in TARGETS]
    output = {
        "probe": "japanese-feed-production-preview-v1",
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
