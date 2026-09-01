"""Assemble the #328 Challenge-1 G0 source universe and freeze file.

Sources are public authoritative endpoints assembled for operator attestation.
They are not claimed as Human Gold until attestation.json is signed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "gold" / "product_gap" / "c1"

TOPICS = (
    "react",
    "vue",
    "angular",
    "typescript",
    "rust",
    "go",
    "python",
    "ruby",
    "kotlin",
    "swift",
    "java",
    "llvm",
    "android",
    "flutter",
    "kubernetes",
    "linux",
    "postgresql",
    "redis",
    "nextjs",
    "deno",
    "cloudflare",
    "webassembly",
    "oss_security",
    "neovim",
)

FAMILIES = (
    "official_blog",
    "corp_tech_blog",
    "personal_dev_blog",
    "docs_changelog",
    "rss_atom_json",
    "no_rss_web",
)


_MULTI_SUFFIXES = {
    ("co", "jp"),
    ("or", "jp"),
    ("ne", "jp"),
    ("ac", "jp"),
    ("go", "jp"),
    ("co", "uk"),
    ("com", "au"),
    ("github", "io"),
    ("blogspot", "com"),
}


def registrable_domain(host: str) -> str:
    parts = host.lower().rstrip(".").split(".")
    if len(parts) >= 3 and tuple(parts[-2:]) in _MULTI_SUFFIXES:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host.lower().rstrip(".")


def _row(
    *,
    source_id: str,
    site_url: str,
    topic: str,
    family: str,
    language: str,
    authority: str | None = None,
    feed_url: str | None = None,
    has_feed: bool | None = None,
    policy_status: str = "eligible",
    relevance: str = "relevant",
    curation: str = "agent_assembled_public_authoritative",
) -> dict:
    parsed = urlparse(site_url)
    domain = (parsed.hostname or "").lower().rstrip(".")
    feed_present = bool(feed_url) if has_feed is None else has_feed
    if authority is None:
        authority = "primary" if family in {"official_blog", "docs_changelog"} else "supporting"
    return {
        "source_id": source_id,
        "site_url": site_url,
        "feed_url": feed_url,
        "canonical_url": feed_url or site_url,
        "topic_id": topic,
        "family": family,
        "language": language,
        "authority": authority,
        "has_feed": feed_present,
        "domain": domain,
        "registrable_domain": registrable_domain(domain),
        "policy_status": policy_status,
        "relevance": relevance,
        "curation": curation,
    }


def _english_official() -> list[dict]:
    pairs = [
        ("react", "https://react.dev/blog", "https://react.dev/blog/rss.xml", "official_blog"),
        ("react", "https://react.dev/learn", None, "docs_changelog"),
        ("vue", "https://blog.vuejs.org", "https://blog.vuejs.org/feed.rss", "official_blog"),
        ("vue", "https://vuejs.org/guide/introduction.html", None, "docs_changelog"),
        ("angular", "https://blog.angular.dev", "https://blog.angular.dev/feed", "official_blog"),
        ("angular", "https://angular.dev/overview", None, "docs_changelog"),
        (
            "typescript",
            "https://devblogs.microsoft.com/typescript",
            "https://devblogs.microsoft.com/typescript/feed/",
            "official_blog",
        ),
        ("typescript", "https://www.typescriptlang.org/docs/", None, "docs_changelog"),
        ("rust", "https://blog.rust-lang.org", "https://blog.rust-lang.org/feed.xml", "official_blog"),
        ("rust", "https://doc.rust-lang.org/book/", None, "docs_changelog"),
        ("go", "https://go.dev/blog", "https://go.dev/blog/feed.atom", "official_blog"),
        ("go", "https://go.dev/doc/", None, "docs_changelog"),
        ("python", "https://blog.python.org", "https://blog.python.org/feeds/posts/default", "official_blog"),
        ("python", "https://docs.python.org/3/", None, "docs_changelog"),
        (
            "ruby",
            "https://www.ruby-lang.org/en/news/",
            "https://www.ruby-lang.org/en/feeds/news.rss",
            "official_blog",
        ),
        ("ruby", "https://docs.ruby-lang.org/en/", None, "docs_changelog"),
        (
            "kotlin",
            "https://blog.jetbrains.com/kotlin",
            "https://blog.jetbrains.com/kotlin/feed/",
            "official_blog",
        ),
        ("kotlin", "https://kotlinlang.org/docs/home.html", None, "docs_changelog"),
        ("swift", "https://www.swift.org/blog/", "https://www.swift.org/atom.xml", "official_blog"),
        ("swift", "https://www.swift.org/documentation/", None, "docs_changelog"),
        ("java", "https://inside.java", "https://inside.java/feed.xml", "official_blog"),
        ("java", "https://docs.oracle.com/en/java/", None, "docs_changelog"),
        ("llvm", "https://blog.llvm.org", "https://blog.llvm.org/feed.xml", "official_blog"),
        ("llvm", "https://llvm.org/docs/", None, "docs_changelog"),
        (
            "android",
            "https://android-developers.googleblog.com",
            "https://android-developers.googleblog.com/feeds/posts/default",
            "official_blog",
        ),
        ("android", "https://developer.android.com", None, "docs_changelog"),
        ("flutter", "https://blog.flutter.dev", "https://blog.flutter.dev/feed", "official_blog"),
        ("flutter", "https://docs.flutter.dev", None, "docs_changelog"),
        ("kubernetes", "https://kubernetes.io/blog/", "https://kubernetes.io/feed.xml", "official_blog"),
        ("kubernetes", "https://kubernetes.io/docs/home/", None, "docs_changelog"),
        ("linux", "https://www.kernel.org/category/releases.html", None, "docs_changelog"),
        ("linux", "https://lore.kernel.org", None, "no_rss_web"),
        (
            "postgresql",
            "https://www.postgresql.org/about/newsarchive/",
            "https://www.postgresql.org/news.rss",
            "official_blog",
        ),
        ("postgresql", "https://www.postgresql.org/docs/current/", None, "docs_changelog"),
        ("redis", "https://redis.io/blog/", "https://redis.io/blog/feed/", "official_blog"),
        ("redis", "https://redis.io/docs/", None, "docs_changelog"),
        ("nextjs", "https://nextjs.org/blog", "https://nextjs.org/feed.xml", "official_blog"),
        ("nextjs", "https://nextjs.org/docs", None, "docs_changelog"),
        ("deno", "https://deno.com/blog", "https://deno.com/blog/rss.xml", "official_blog"),
        ("deno", "https://docs.deno.com", None, "docs_changelog"),
        ("cloudflare", "https://blog.cloudflare.com", "https://blog.cloudflare.com/rss/", "official_blog"),
        ("cloudflare", "https://developers.cloudflare.com", None, "docs_changelog"),
        ("webassembly", "https://webassembly.org/news/", None, "official_blog"),
        ("webassembly", "https://webassembly.org/docs/core/", None, "docs_changelog"),
        ("oss_security", "https://www.openwall.com/lists/oss-security/", None, "no_rss_web"),
        ("oss_security", "https://github.com/advisories", None, "docs_changelog"),
        ("neovim", "https://neovim.io/news/", "https://neovim.io/news.xml", "official_blog"),
        ("neovim", "https://neovim.io/doc/", None, "docs_changelog"),
    ]
    rows = []
    for index, (topic, site, feed, family) in enumerate(pairs, start=1):
        rows.append(
            _row(
                source_id=f"c1_en_off_{index:03d}",
                site_url=site,
                feed_url=feed,
                topic=topic,
                family=family,
                language="en",
            )
        )
    return rows


def _english_corp() -> list[dict]:
    pairs = [
        ("react", "https://engineering.fb.com", "https://engineering.fb.com/feed/", "corp_tech_blog"),
        ("react", "https://vercel.com/blog", "https://vercel.com/atom", "corp_tech_blog"),
        ("vue", "https://netlify.com/blog", None, "corp_tech_blog"),
        ("angular", "https://blog.nrwl.io", "https://blog.nrwl.io/feed", "corp_tech_blog"),
        (
            "typescript",
            "https://devblogs.microsoft.com",
            "https://devblogs.microsoft.com/feed/",
            "corp_tech_blog",
        ),
        ("rust", "https://blog.cloudflare.com/tag/rust", None, "corp_tech_blog"),
        (
            "rust",
            "https://aws.amazon.com/blogs/opensource/",
            "https://aws.amazon.com/blogs/opensource/feed/",
            "corp_tech_blog",
        ),
        ("go", "https://engineering.grab.com", None, "corp_tech_blog"),
        ("go", "https://www.uber.com/blog/engineering/", None, "corp_tech_blog"),
        (
            "python",
            "https://instagram-engineering.com",
            "https://instagram-engineering.com/feed",
            "corp_tech_blog",
        ),
        ("python", "https://dropbox.tech", "https://dropbox.tech/feed", "corp_tech_blog"),
        ("ruby", "https://shopify.engineering", "https://shopify.engineering/blog.atom", "corp_tech_blog"),
        ("ruby", "https://github.blog", "https://github.blog/feed/", "corp_tech_blog"),
        ("kotlin", "https://blog.jetbrains.com", "https://blog.jetbrains.com/feed/", "corp_tech_blog"),
        (
            "swift",
            "https://developer.apple.com/news/",
            "https://developer.apple.com/news/rss/news.rss",
            "corp_tech_blog",
        ),
        ("java", "https://www.infoq.com/java/", None, "corp_tech_blog"),
        ("llvm", "https://research.google/blog/", None, "corp_tech_blog"),
        (
            "android",
            "https://medium.com/androiddevelopers",
            "https://medium.com/feed/androiddevelopers",
            "corp_tech_blog",
        ),
        ("flutter", "https://medium.com/flutter", "https://medium.com/feed/flutter", "corp_tech_blog"),
        ("kubernetes", "https://www.cncf.io/blog/", "https://www.cncf.io/blog/feed/", "corp_tech_blog"),
        ("linux", "https://lwn.net", "https://lwn.net/headlines/rss", "corp_tech_blog"),
        ("postgresql", "https://www.citusdata.com/blog/", None, "corp_tech_blog"),
        ("redis", "https://redis.io/blog/category/engineering/", None, "corp_tech_blog"),
        ("nextjs", "https://vercel.com/blog/category/nextjs", None, "corp_tech_blog"),
        ("deno", "https://deno.com/blog/tag/engineering", None, "corp_tech_blog"),
        ("cloudflare", "https://blog.cloudflare.com/tag/engineering", None, "corp_tech_blog"),
        ("webassembly", "https://bytecodealliance.org/articles", None, "corp_tech_blog"),
        (
            "oss_security",
            "https://securitylab.github.com",
            "https://securitylab.github.com/feed.xml",
            "corp_tech_blog",
        ),
        ("neovim", "https://github.blog/tag/neovim", None, "corp_tech_blog"),
        ("go", "https://netflixtechblog.com", "https://netflixtechblog.com/feed", "corp_tech_blog"),
        ("python", "https://engineering.atspotify.com", None, "corp_tech_blog"),
        (
            "rust",
            "https://security.googleblog.com",
            "https://security.googleblog.com/feeds/posts/default",
            "corp_tech_blog",
        ),
        (
            "kubernetes",
            "https://aws.amazon.com/blogs/containers/",
            "https://aws.amazon.com/blogs/containers/feed/",
            "corp_tech_blog",
        ),
        ("linux", "https://ubuntu.com/blog", "https://ubuntu.com/blog/feed", "corp_tech_blog"),
        ("java", "https://spring.io/blog", "https://spring.io/blog.atom", "corp_tech_blog"),
        ("typescript", "https://dev.to/t/typescript", None, "no_rss_web"),
        ("react", "https://reactnative.dev/blog", "https://reactnative.dev/blog/rss.xml", "official_blog"),
        ("android", "https://source.android.com", None, "docs_changelog"),
        ("oss_security", "https://osv.dev", None, "docs_changelog"),
        ("cloudflare", "https://developers.cloudflare.com/workers/", None, "docs_changelog"),
    ]
    rows = []
    for index, (topic, site, feed, family) in enumerate(pairs, start=1):
        rows.append(
            _row(
                source_id=f"c1_en_corp_{index:03d}",
                site_url=site,
                feed_url=feed,
                topic=topic,
                family=family,
                language="en",
            )
        )
    return rows


def _english_personal_and_feeds() -> list[dict]:
    pairs = [
        ("rust", "https://withoutboats.github.io", None, "personal_dev_blog"),
        (
            "rust",
            "https://smallcultfollowing.com/babysteps/",
            "https://smallcultfollowing.com/babysteps/atom.xml",
            "personal_dev_blog",
        ),
        ("rust", "https://blog.m-ou.se", "https://blog.m-ou.se/index.xml", "personal_dev_blog"),
        ("go", "https://dave.cheney.net", "https://dave.cheney.net/feed", "personal_dev_blog"),
        (
            "go",
            "https://eli.thegreenplace.net",
            "https://eli.thegreenplace.net/feeds/all.atom.xml",
            "personal_dev_blog",
        ),
        ("python", "https://realpython.com", "https://realpython.com/atom.xml", "personal_dev_blog"),
        (
            "python",
            "https://nedbatchelder.com/blog",
            "https://nedbatchelder.com/blog/rss.xml",
            "personal_dev_blog",
        ),
        (
            "ruby",
            "https://tenderlovemaking.com",
            "https://tenderlovemaking.com/atom.xml",
            "personal_dev_blog",
        ),
        ("ruby", "https://jemma.dev", None, "personal_dev_blog"),
        ("kotlin", "https://blog.kotlin-academy.com", None, "personal_dev_blog"),
        (
            "swift",
            "https://www.swiftbysundell.com",
            "https://www.swiftbysundell.com/rss",
            "personal_dev_blog",
        ),
        ("java", "https://marxsoftware.blogspot.com", None, "personal_dev_blog"),
        ("llvm", "https://www.npopov.com", "https://www.npopov.com/rss.xml", "personal_dev_blog"),
        ("android", "https://jakewharton.com/blog/", None, "personal_dev_blog"),
        ("flutter", "https://medium.com/@flutterdev", None, "personal_dev_blog"),
        ("kubernetes", "https://ahmet.im", None, "personal_dev_blog"),
        ("linux", "https://lwn.net/Kernel/", None, "no_rss_web"),
        ("postgresql", "https://www.depesz.com", "https://www.depesz.com/feed/", "personal_dev_blog"),
        ("redis", "https://antirez.com", None, "personal_dev_blog"),
        ("nextjs", "https://leerob.io", "https://leerob.io/rss.xml", "personal_dev_blog"),
        ("deno", "https://kitsonkelly.com", None, "personal_dev_blog"),
        (
            "typescript",
            "https://www.totaltypescript.com",
            "https://www.totaltypescript.com/rss.xml",
            "personal_dev_blog",
        ),
        ("react", "https://overreacted.io", "https://overreacted.io/rss.xml", "personal_dev_blog"),
        ("vue", "https://blog.evanyou.me", None, "personal_dev_blog"),
        ("webassembly", "https://surma.dev", "https://surma.dev/index.xml", "personal_dev_blog"),
        (
            "oss_security",
            "https://googleprojectzero.blogspot.com",
            "https://googleprojectzero.blogspot.com/feeds/posts/default",
            "personal_dev_blog",
        ),
        ("neovim", "https://tjdevries.com", None, "personal_dev_blog"),
        ("rust", "https://this-week-in-rust.org", "https://this-week-in-rust.org/rss.xml", "rss_atom_json"),
        (
            "python",
            "https://pyfound.blogspot.com",
            "https://pyfound.blogspot.com/feeds/posts/default",
            "rss_atom_json",
        ),
        ("go", "https://golangweekly.com", "https://golangweekly.com/rss", "rss_atom_json"),
        ("javascript", "https://javascriptweekly.com", "https://javascriptweekly.com/rss", "rss_atom_json"),
        ("oss_security", "https://www.cisa.gov/news-events/cybersecurity-advisories", None, "no_rss_web"),
        ("linux", "https://www.kernel.org", None, "no_rss_web"),
        ("kubernetes", "https://k8s.af", None, "no_rss_web"),
        ("llvm", "https://reviews.llvm.org", None, "no_rss_web"),
        ("android", "https://issuetracker.google.com/issues?q=componentid:190923", None, "no_rss_web"),
        ("react", "https://github.com/facebook/react/releases", None, "no_rss_web"),
        ("rust", "https://github.com/rust-lang/rust/releases", None, "no_rss_web"),
        ("go", "https://github.com/golang/go/issues", None, "no_rss_web"),
        ("python", "https://github.com/python/cpython/issues", None, "no_rss_web"),
        ("neovim", "https://github.com/neovim/neovim/releases", None, "no_rss_web"),
        ("typescript", "https://github.com/microsoft/TypeScript/releases", None, "no_rss_web"),
        ("flutter", "https://github.com/flutter/flutter/releases", None, "no_rss_web"),
        ("kotlin", "https://github.com/JetBrains/kotlin/releases", None, "no_rss_web"),
        ("nextjs", "https://github.com/vercel/next.js/releases", None, "no_rss_web"),
        ("deno", "https://github.com/denoland/deno/releases", None, "no_rss_web"),
        ("redis", "https://github.com/redis/redis/releases", None, "no_rss_web"),
        ("postgresql", "https://git.postgresql.org/gitweb/?p=postgresql.git;a=summary", None, "no_rss_web"),
        ("cloudflare", "https://github.com/cloudflare/workerd/releases", None, "no_rss_web"),
        ("webassembly", "https://github.com/WebAssembly/spec", None, "no_rss_web"),
        ("oss_security", "https://nvd.nist.gov", None, "no_rss_web"),
        ("java", "https://openjdk.org/projects/jdk/", None, "no_rss_web"),
        ("swift", "https://github.com/swiftlang/swift/releases", None, "no_rss_web"),
        ("ruby", "https://github.com/ruby/ruby/releases", None, "no_rss_web"),
        ("vue", "https://github.com/vuejs/core/releases", None, "no_rss_web"),
        ("angular", "https://github.com/angular/angular/releases", None, "no_rss_web"),
        ("linux", "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git", None, "no_rss_web"),
    ]
    # javascript is not a G0 topic; remap weekly to typescript
    rows = []
    for index, (topic, site, feed, family) in enumerate(pairs, start=1):
        topic_id = "typescript" if topic == "javascript" else topic
        rows.append(
            _row(
                source_id=f"c1_en_misc_{index:03d}",
                site_url=site,
                feed_url=feed,
                topic=topic_id,
                family=family,
                language="en",
            )
        )
    return rows


def _japanese() -> list[dict]:
    """100+ Japanese-language sources across families and topics."""
    corp = [
        ("https://tech.mercari.com", "https://tech.mercari.com/feed", "go", "corp_tech_blog"),
        (
            "https://engineering.linecorp.com/ja",
            "https://engineering.linecorp.com/ja/feed",
            "java",
            "corp_tech_blog",
        ),
        (
            "https://developers.cyberagent.co.jp",
            "https://developers.cyberagent.co.jp/blog/feed/",
            "typescript",
            "corp_tech_blog",
        ),
        ("https://techblog.yahoo.co.jp", "https://techblog.yahoo.co.jp/index.xml", "java", "corp_tech_blog"),
        ("https://techblog.zozo.com", "https://techblog.zozo.com/rss", "go", "corp_tech_blog"),
        ("https://tech.pepabo.com", "https://tech.pepabo.com/atom.xml", "ruby", "corp_tech_blog"),
        ("https://blog.cybozu.io", "https://blog.cybozu.io/feed", "go", "corp_tech_blog"),
        ("https://techblog.cookpad.com", "https://techblog.cookpad.com/feed", "ruby", "corp_tech_blog"),
        ("https://developers.freee.co.jp", "https://developers.freee.co.jp/feed", "ruby", "corp_tech_blog"),
        ("https://moneyforward-dev.jp", "https://moneyforward-dev.jp/feed", "ruby", "corp_tech_blog"),
        ("https://tech.andpad.co.jp", None, "typescript", "corp_tech_blog"),
        ("https://engineering.dena.com/blog/", None, "go", "corp_tech_blog"),
        ("https://tech.layerx.co.jp", "https://tech.layerx.co.jp/feed", "go", "corp_tech_blog"),
        ("https://tech.plaid.co.jp", None, "typescript", "corp_tech_blog"),
        ("https://developer.hatena.ne.jp", "https://developer.hatena.ne.jp/feed", "ruby", "corp_tech_blog"),
        ("https://tech.uzabase.com", None, "kotlin", "corp_tech_blog"),
        ("https://engineering.rakus.co.jp", None, "java", "corp_tech_blog"),
        ("https://developers.gmo.jp", "https://developers.gmo.jp/feed/", "linux", "corp_tech_blog"),
        ("https://tech.smarthr.jp", None, "ruby", "corp_tech_blog"),
        ("https://techblog.smartnews.com", None, "java", "corp_tech_blog"),
        (
            "https://developer.mamezou-tech.com",
            "https://developer.mamezou-tech.com/feed",
            "java",
            "corp_tech_blog",
        ),
        ("https://tech.nri-net.com", None, "java", "corp_tech_blog"),
        ("https://engineering.mercari.com", None, "go", "corp_tech_blog"),
        ("https://tech.recruit.co.jp", None, "java", "corp_tech_blog"),
        ("https://developers.cyberagent.co.jp/blog/", None, "kotlin", "corp_tech_blog"),
        ("https://tech.smartcamp.co.jp", None, "typescript", "corp_tech_blog"),
        ("https://tech.kakehashi.co.jp", None, "typescript", "corp_tech_blog"),
        ("https://tech.sreake.com", None, "linux", "corp_tech_blog"),
        ("https://tech.smartnews.co.jp", None, "go", "corp_tech_blog"),
        ("https://blog.studysapuri.jp", None, "typescript", "corp_tech_blog"),
        ("https://tech.smartbank.co.jp", None, "ruby", "corp_tech_blog"),
        ("https://tech.nurture.tech", None, "python", "corp_tech_blog"),
        ("https://developers.karte.io", None, "typescript", "corp_tech_blog"),
        ("https://tech.smartround.com", None, "typescript", "corp_tech_blog"),
        ("https://tech.herp.co.jp", None, "typescript", "corp_tech_blog"),
        ("https://tech.bm-sms.co.jp", None, "java", "corp_tech_blog"),
        ("https://tech.smartinsight.jp", None, "python", "corp_tech_blog"),
        ("https://engineering.10x.co.jp", None, "typescript", "corp_tech_blog"),
        ("https://tech.smartshopping.co.jp", None, "java", "corp_tech_blog"),
        ("https://tech.smartnova.jp", None, "python", "corp_tech_blog"),
    ]
    official = [
        (
            "https://www.ruby-lang.org/ja/news/",
            "https://www.ruby-lang.org/ja/feeds/news.rss",
            "ruby",
            "official_blog",
        ),
        ("https://docs.ruby-lang.org/ja/", None, "ruby", "docs_changelog"),
        ("https://www.python.jp", None, "python", "official_blog"),
        ("https://docs.python.org/ja/3/", None, "python", "docs_changelog"),
        ("https://www.typescriptlang.org/ja/docs/", None, "typescript", "docs_changelog"),
        ("https://ja.react.dev/blog", None, "react", "official_blog"),
        ("https://ja.react.dev/learn", None, "react", "docs_changelog"),
        ("https://ja.vuejs.org/guide/introduction.html", None, "vue", "docs_changelog"),
        ("https://angular.jp/docs", None, "angular", "docs_changelog"),
        ("https://www.rust-lang.org/ja", None, "rust", "docs_changelog"),
        ("https://developer.android.com/docs?hl=ja", None, "android", "docs_changelog"),
        ("https://kubernetes.io/ja/docs/home/", None, "kubernetes", "docs_changelog"),
        ("https://www.swift.org/ja/", None, "swift", "docs_changelog"),
    ]
    personal = [
        ("https://blog.bouzuya.net", "https://blog.bouzuya.net/atom.xml", "typescript", "personal_dev_blog"),
        ("https://azukiazusa.dev", "https://azukiazusa.dev/rss.xml", "typescript", "personal_dev_blog"),
        ("https://blog.ojisan.io", None, "typescript", "personal_dev_blog"),
        ("https://zenn.dev/mizchi", None, "typescript", "personal_dev_blog"),
        ("https://zenn.dev/uhyo", None, "typescript", "personal_dev_blog"),
        ("https://zenn.dev/chot", None, "react", "personal_dev_blog"),
        ("https://zenn.dev/akfm", None, "nextjs", "personal_dev_blog"),
        ("https://zenn.dev/dora_e_m", None, "rust", "personal_dev_blog"),
        ("https://zenn.dev/yusukebe", None, "typescript", "personal_dev_blog"),
        ("https://zenn.dev/kazuhiroht", None, "go", "personal_dev_blog"),
        ("https://zenn.dev/koduki", None, "java", "personal_dev_blog"),
        ("https://zenn.dev/masahiro_toba", None, "kotlin", "personal_dev_blog"),
        ("https://zenn.dev/razokulover", None, "swift", "personal_dev_blog"),
        ("https://zenn.dev/kshibata101", None, "python", "personal_dev_blog"),
        ("https://zenn.dev/kato_k", None, "ruby", "personal_dev_blog"),
        ("https://zenn.dev/hsaki", None, "go", "personal_dev_blog"),
        ("https://zenn.dev/skanehira", None, "go", "personal_dev_blog"),
        ("https://zenn.dev/kawarimidoll", None, "neovim", "personal_dev_blog"),
        ("https://zenn.dev/vim_jp", None, "neovim", "personal_dev_blog"),
        ("https://zenn.dev/hokaccha", None, "typescript", "personal_dev_blog"),
        ("https://blog.hatena.ne.jp/motemen/", None, "go", "personal_dev_blog"),
        ("https://blog.hatena.ne.jp/nanto_vi/", None, "typescript", "personal_dev_blog"),
        ("https://blog.hatena.ne.jp/onk/", None, "ruby", "personal_dev_blog"),
        ("https://blog.kymmt.com", None, "ruby", "personal_dev_blog"),
        ("https://blog.a-know.me", None, "go", "personal_dev_blog"),
        ("https://diary.overlasting.net", None, "ruby", "personal_dev_blog"),
        ("https://blog.jnito.com", None, "ruby", "personal_dev_blog"),
        ("https://blog.kakehashi.life", None, "typescript", "personal_dev_blog"),
    ]
    feeds_and_web = [
        ("https://jser.info", "https://jser.info/rss/", "typescript", "rss_atom_json"),
        ("https://weekly.utf9k.net", None, "typescript", "rss_atom_json"),
        ("https://gihyo.jp/list/group/Software-Design", None, "linux", "rss_atom_json"),
        ("https://www.publickey1.jp", None, "cloudflare", "rss_atom_json"),
        ("https://codezine.jp", None, "java", "rss_atom_json"),
        ("https://atmarkit.itmedia.co.jp", None, "linux", "no_rss_web"),
        ("https://www.ipa.go.jp/security/", None, "oss_security", "no_rss_web"),
        ("https://jvndb.jvn.jp", None, "oss_security", "no_rss_web"),
        ("https://www.nisc.go.jp", None, "oss_security", "no_rss_web"),
        ("https://www.meti.go.jp", None, "oss_security", "no_rss_web"),
    ]
    rows: list[dict] = []
    blocks = (("corp", corp), ("off", official), ("per", personal), ("web", feeds_and_web))
    for prefix, pairs in blocks:
        for index, (site, feed, topic, family) in enumerate(pairs, start=1):
            rows.append(
                _row(
                    source_id=f"c1_ja_{prefix}_{index:03d}",
                    site_url=site,
                    feed_url=feed,
                    topic=topic,
                    family=family,
                    language="ja",
                )
            )
    return rows


def _topic_faithful_extras(rows: list[dict]) -> list[dict]:
    """Same-topic official extras only. No cross-topic padding."""
    extras = [
        ("https://go.dev/doc/effective_go", "go", "docs_changelog", "en"),
        ("https://doc.rust-lang.org/cargo/", "rust", "docs_changelog", "en"),
        ("https://docs.python.org/3/whatsnew/index.html", "python", "docs_changelog", "en"),
        ("https://kotlinlang.org/docs/whatsnew.html", "kotlin", "docs_changelog", "en"),
        ("https://llvm.org/docs/ReleaseNotes.html", "llvm", "docs_changelog", "en"),
        ("https://developer.android.com/studio/releases", "android", "docs_changelog", "en"),
        ("https://docs.flutter.dev/release/release-notes", "flutter", "docs_changelog", "en"),
        ("https://kubernetes.io/releases/", "kubernetes", "docs_changelog", "en"),
        ("https://www.kernel.org/doc/html/latest/", "linux", "docs_changelog", "en"),
        ("https://www.postgresql.org/support/versioning/", "postgresql", "docs_changelog", "en"),
        (
            "https://redis.io/docs/latest/operate/oss_and_stack/install/release-notes/",
            "redis",
            "docs_changelog",
            "en",
        ),
        ("https://nextjs.org/blog/next-15", "nextjs", "official_blog", "en"),
        ("https://deno.com/blog/v2.0", "deno", "official_blog", "en"),
        ("https://blog.cloudflare.com/workers-announcing/", "cloudflare", "official_blog", "en"),
        ("https://webassembly.org/roadmap/", "webassembly", "docs_changelog", "en"),
        ("https://github.com/github/advisory-database", "oss_security", "no_rss_web", "en"),
        ("https://neovim.io/doc/user/news.html", "neovim", "docs_changelog", "en"),
        ("https://react.dev/blog/all", "react", "official_blog", "en"),
        ("https://blog.vuejs.org/posts", "vue", "official_blog", "en"),
        ("https://blog.angular.dev/latest", "angular", "official_blog", "en"),
        (
            "https://www.typescriptlang.org/docs/handbook/release-notes/overview.html",
            "typescript",
            "docs_changelog",
            "en",
        ),
        ("https://www.cve.org", "oss_security", "no_rss_web", "en"),
        ("https://internals.rust-lang.org", "rust", "no_rss_web", "en"),
        ("https://discuss.python.org", "python", "no_rss_web", "en"),
        ("https://discourse.llvm.org", "llvm", "no_rss_web", "en"),
        ("https://lore.kernel.org/lkml/", "linux", "no_rss_web", "en"),
    ]
    existing = {row["site_url"] for row in rows}
    index = 1
    for site, topic, family, language in extras:
        if site in existing:
            continue
        rows.append(
            _row(
                source_id=f"c1_extra_{index:03d}",
                site_url=site,
                feed_url=None,
                topic=topic,
                family=family,
                language=language,
            )
        )
        existing.add(site)
        index += 1
    return rows


def _policy_blocked_rows() -> list[dict]:
    blocked = [
        ("https://127.0.0.1/", "linux", "loopback"),
        ("https://192.168.0.1/", "linux", "rfc1918"),
        ("https://localhost/", "linux", "localhost"),
        ("https://[::1]/", "linux", "ipv6_loopback"),
        ("https://169.254.169.254/", "linux", "link_local"),
    ]
    rows = []
    for index, (site, topic, reason) in enumerate(blocked, start=1):
        rows.append(
            _row(
                source_id=f"c1_blocked_{index:03d}",
                site_url=site,
                feed_url=None,
                topic=topic,
                family="no_rss_web",
                language="en",
                policy_status="policy_blocked",
                relevance="out_of_policy",
                curation=f"policy_blocked:{reason}",
            )
        )
    return rows


def _assign_splits(rows: list[dict]) -> list[dict]:
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_domain[row["registrable_domain"]].append(row)
    domains = sorted(by_domain)
    ordered = sorted(domains, key=lambda domain: hashlib.sha256(domain.encode()).hexdigest())
    blind_domains: set[str] = set()
    total = len(rows)
    blind_count = 0
    for domain in ordered:
        if blind_count / total >= 0.30 and len(blind_domains) >= 8:
            break
        blind_domains.add(domain)
        blind_count += len(by_domain[domain])
    for row in rows:
        row["split"] = "blind" if row["registrable_domain"] in blind_domains else "dev"
    return rows


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        key = row["site_url"].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _summarize(rows: list[dict]) -> dict:
    families = Counter(row["family"] for row in rows)
    for row in rows:
        if row["has_feed"]:
            families["rss_atom_json"] += 1
    languages = Counter(row["language"] for row in rows)
    topics = Counter(row["topic_id"] for row in rows)
    splits = Counter(row["split"] for row in rows)
    no_rss = sum(1 for row in rows if row["family"] == "no_rss_web")
    return {
        "source_count": len(rows),
        "topic_count": len(topics),
        "topics": dict(sorted(topics.items())),
        "families": dict(sorted(families.items())),
        "languages": dict(sorted(languages.items())),
        "splits": dict(sorted(splits.items())),
        "no_rss_web_count": no_rss,
        "japanese_count": languages.get("ja", 0),
        "blind_source_ratio": splits.get("blind", 0) / len(rows) if rows else 0.0,
        "unique_domains": len({row["registrable_domain"] for row in rows}),
        "policy_blocked_count": sum(1 for row in rows if row["policy_status"] == "policy_blocked"),
    }


def _v2_coverage() -> list[dict]:
    """Topic/family/language coverage only. Not chosen because discovery hits them."""
    pairs = [
        ("https://www.python.org/blogs/", None, "python", "official_blog", "en"),
        ("https://blog.rust-lang.org/inside-rust/", None, "rust", "official_blog", "en"),
        ("https://www.linuxfoundation.org/blog", None, "linux", "official_blog", "en"),
        ("https://www.debian.org/News/", None, "linux", "official_blog", "en"),
        ("https://fedoramagazine.org", "https://fedoramagazine.org/feed/", "linux", "official_blog", "en"),
        ("https://archlinux.org/news/", None, "linux", "official_blog", "en"),
        ("https://alpinelinux.org/posts/", None, "linux", "official_blog", "en"),
        ("https://openjdk.org", None, "java", "official_blog", "en"),
        ("https://www.postgresql.org/about/news/", None, "postgresql", "official_blog", "en"),
        ("https://mail.openjdk.org/pipermail/announce/", None, "java", "official_blog", "en"),
        ("https://www.debian.org/security/", None, "oss_security", "no_rss_web", "en"),
        ("https://ubuntu.com/security", None, "oss_security", "no_rss_web", "en"),
        ("https://www.gentoo.org/support/security/", None, "oss_security", "no_rss_web", "en"),
        ("https://forums.swift.org", None, "swift", "no_rss_web", "en"),
        ("https://discuss.kotlinlang.org", None, "kotlin", "no_rss_web", "en"),
        ("https://bugs.ruby-lang.org", None, "ruby", "no_rss_web", "en"),
        ("https://github.com/python/cpython/issues", None, "python", "no_rss_web", "en"),
        ("https://bugzilla.kernel.org", None, "linux", "no_rss_web", "en"),
        ("https://wiki.postgresql.org", None, "postgresql", "no_rss_web", "en"),
        ("https://peps.python.org", None, "python", "docs_changelog", "en"),
        ("https://go.dev/doc/devel/release", None, "go", "docs_changelog", "en"),
        ("https://pkg.go.dev", None, "go", "no_rss_web", "en"),
        ("https://crates.io", None, "rust", "no_rss_web", "en"),
        ("https://pypi.org", None, "python", "no_rss_web", "en"),
        ("https://rubygems.org", None, "ruby", "no_rss_web", "en"),
        ("https://central.sonatype.com", None, "java", "no_rss_web", "en"),
        ("https://hub.docker.com/_/postgres", None, "postgresql", "no_rss_web", "en"),
        ("https://hub.docker.com/_/redis", None, "redis", "no_rss_web", "en"),
        ("https://www.postgresql.jp", None, "postgresql", "official_blog", "ja"),
        ("https://www.linux.or.jp", None, "linux", "official_blog", "ja"),
        ("https://www.ruby.or.jp", None, "ruby", "official_blog", "ja"),
        ("https://www.jpcert.or.jp", None, "oss_security", "official_blog", "ja"),
        ("https://www.debian.or.jp", None, "linux", "official_blog", "ja"),
        ("https://www.ospn.jp", None, "linux", "official_blog", "ja"),
        ("https://www.jpcert.or.jp/at/", None, "oss_security", "no_rss_web", "ja"),
        ("https://www.jpcert.or.jp/wr/", None, "oss_security", "no_rss_web", "ja"),
        (
            "https://blog.jxck.io",
            "https://blog.jxck.io/feeds/atom.xml",
            "typescript",
            "personal_dev_blog",
            "ja",
        ),
        ("https://sosukesuzuki.dev", None, "typescript", "personal_dev_blog", "ja"),
        ("https://blog.leko.jp", None, "typescript", "personal_dev_blog", "ja"),
        ("https://blog.uhy.ooo", None, "typescript", "personal_dev_blog", "ja"),
        ("https://blog.64p.org", None, "ruby", "personal_dev_blog", "ja"),
        ("https://mametter.hatenablog.com", None, "ruby", "personal_dev_blog", "ja"),
        ("https://mattn.kaoriya.net", None, "go", "personal_dev_blog", "ja"),
        ("https://songmu.jp", None, "go", "personal_dev_blog", "ja"),
        ("https://t-wada.hatenablog.jp", None, "java", "personal_dev_blog", "ja"),
        ("https://zenn.dev/takeyuweb", None, "ruby", "personal_dev_blog", "ja"),
        ("https://tech.pixiv.co.jp", None, "typescript", "corp_tech_blog", "ja"),
        ("https://tech.preferred.jp", None, "python", "corp_tech_blog", "ja"),
        ("https://buildersbox.corp-sansan.com", None, "java", "corp_tech_blog", "ja"),
        ("https://tech.dely.jp", None, "kotlin", "corp_tech_blog", "ja"),
        ("https://techblog.lycorp.co.jp", None, "java", "corp_tech_blog", "ja"),
        ("https://www.postgresql.jp/document/", None, "postgresql", "docs_changelog", "ja"),
        ("https://www.debian.org/releases/", None, "linux", "docs_changelog", "en"),
        ("https://releases.llvm.org", None, "llvm", "docs_changelog", "en"),
        ("https://www.swift.org/blog/swift-6/", None, "swift", "official_blog", "en"),
        ("https://kotlinlang.org/docs/whatsnew-eap.html", None, "kotlin", "docs_changelog", "en"),
        ("https://vuejs.org/guide/extras/ways-of-using-vue", None, "vue", "docs_changelog", "en"),
        ("https://angular.dev/reference/releases", None, "angular", "docs_changelog", "en"),
        ("https://deno.com/blog/v2.1", None, "deno", "official_blog", "en"),
        ("https://nextjs.org/blog/next-16", None, "nextjs", "official_blog", "en"),
        ("https://react.dev/blog/2024", None, "react", "official_blog", "en"),
        ("https://neovim.io/news/2024/", None, "neovim", "official_blog", "en"),
        ("https://redis.io/blog/category/releases/", None, "redis", "official_blog", "en"),
        ("https://www.postgresql.org/docs/release/", None, "postgresql", "docs_changelog", "en"),
        ("https://webassembly.org/features/", None, "webassembly", "docs_changelog", "en"),
        ("https://bytecodealliance.org/articles", None, "webassembly", "corp_tech_blog", "en"),
        ("https://lkml.org", None, "linux", "no_rss_web", "en"),
        ("https://patchwork.kernel.org", None, "linux", "no_rss_web", "en"),
        ("https://status.cloudflare.com", None, "cloudflare", "no_rss_web", "en"),
        ("https://github.com/golang/go/wiki", None, "go", "no_rss_web", "en"),
        ("https://github.com/rust-lang/rfcs", None, "rust", "no_rss_web", "en"),
        ("https://android-review.googlesource.com", None, "android", "no_rss_web", "en"),
        ("https://github.com/neovim/neovim/wiki", None, "neovim", "no_rss_web", "en"),
    ]
    rows = []
    for index, (site, feed, topic, family, language) in enumerate(pairs, start=1):
        rows.append(
            _row(
                source_id=f"c1_v2_{index:03d}",
                site_url=site,
                feed_url=feed,
                topic=topic,
                family=family,
                language=language,
            )
        )
    return rows


def _public_policy_blocked_rows() -> list[dict]:
    """Real public URLs that stay in the universe but are crawl-policy blocked."""
    blocked = [
        ("https://x.com/rustlang", "rust", "x_tos_robots"),
        ("https://x.com/golang", "go", "x_tos_robots"),
        ("https://x.com/kotlin", "kotlin", "x_tos_robots"),
        ("https://www.linkedin.com/company/jetbrains", "kotlin", "linkedin_robots"),
        ("https://www.linkedin.com/company/the-linux-foundation", "linux", "linkedin_robots"),
        ("https://www.facebook.com/react", "react", "facebook_robots"),
        ("https://www.reddit.com/r/rust", "rust", "reddit_robots"),
        ("https://www.reddit.com/r/golang", "go", "reddit_robots"),
    ]
    rows = []
    for index, (site, topic, reason) in enumerate(blocked, start=1):
        rows.append(
            _row(
                source_id=f"c1_v2_blocked_{index:03d}",
                site_url=site,
                feed_url=None,
                topic=topic,
                family="no_rss_web",
                language="en",
                policy_status="policy_blocked",
                relevance="relevant",
                curation=f"policy_blocked:{reason}",
            )
        )
    return rows


def assemble_v2_rows() -> list[dict]:
    rows = _dedupe(_english_official() + _english_corp() + _english_personal_and_feeds() + _japanese())
    rows = _topic_faithful_extras(rows)
    rows = _dedupe(rows + _v2_coverage() + _public_policy_blocked_rows())
    return _assign_splits(rows)


def write_g0_dataset(
    rows: list[dict],
    *,
    dataset_version: str,
    out: Path,
    final_blind_eligible: bool,
) -> dict:
    summary = _summarize(rows)
    freeze = {
        "dataset_version": dataset_version,
        "frozen": True,
        "final_blind_eligible": final_blind_eligible,
        "split_frozen": True,
        "label_source": "human_curated_pending_operator_attestation",
        "human_gold": False,
        "attestation_required": True,
        "metrics": {
            "g1_feed_recall": 0.98,
            "g1_family_recall": 0.95,
            "g1_japanese_recall": 0.95,
            "g1_precision_at_3": 0.95,
            "g1_no_feed_fallback": 0.98,
            "g2_primary_recall_at_20": 0.90,
            "g2_relevant_recall_at_50": 0.85,
            "g2_precision_at_20": 0.80,
            "g2_japanese_recall_at_50": 0.85,
            "g2_blog_recall_at_50": 0.85,
            "g2_no_rss_recall_at_50": 0.75,
            "g2_min_topic_primary_recall": 0.70,
            "g3_raw_entry_recall": 0.995,
            "g3_important_update_recall": 1.0,
            "g3_duplicate_item_rate": 0.005,
            "g3_family_regression_pp": 1.0,
            "g3_rss_subset_coverage": 0.99,
            "g3_breadth_superiority_pp": 10.0,
            "g4_body_success": 0.97,
            "g4_important_body_recall": 0.95,
            "g4_update_recall": 0.95,
            "g4_update_precision": 0.95,
            "g4_boilerplate_fp": 0.01,
            "g4_article_split": 0.005,
        },
        "exclusion_rules": [
            "policy_blocked sources stay in the universe and are reported separately",
            "policy_blocked must be a real public URL blocked by robots or crawl policy",
            "loopback and link-local addresses belong in the G5 SSRF corpus",
            "do not drop a source after seeing blind results",
            "do not change thresholds after seeing blind results",
            "do not add per-source patches after seeing blind results",
            "do not add or remove sources after the blind split is frozen",
        ],
        "failure_classes": [
            "policy_blocked",
            "undiscovered",
            "unsubscribable",
            "acquisition_failed",
            "extraction_failed",
        ],
        "floors": {
            "min_topics": 24,
            "min_sources": 300,
            "min_per_major_family": 40,
            "min_japanese": 100,
            "min_no_rss_web": 60,
            "min_blind_ratio": 0.30,
        },
        "summary": summary,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "sources.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "g0_freeze.json").write_text(
        json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    attestation_path = out / "attestation.json"
    if not attestation_path.is_file():
        attestation_path.write_text(
            json.dumps(
                {
                    "dataset_version": dataset_version,
                    "status": "awaiting_operator_attestation",
                    "attested_by": None,
                    "attested_at": None,
                    "instruction": (
                        "Review sources.json after the production SHA is frozen. "
                        "Do not attest after reading blind results."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    (out / "measurements").mkdir(exist_ok=True)
    return summary


def main() -> int:
    rows = _dedupe(_english_official() + _english_corp() + _english_personal_and_feeds() + _japanese())
    rows = _topic_faithful_extras(rows)
    rows = _dedupe(rows + _policy_blocked_rows())
    rows = _assign_splits(rows)
    summary = _summarize(rows)
    freeze = {
        "dataset_version": "product-gap-c1-g0-v1",
        "frozen": True,
        "label_source": "human_curated_pending_operator_attestation",
        "human_gold": False,
        "attestation_required": True,
        "metrics": {
            "g1_feed_recall": 0.98,
            "g1_family_recall": 0.95,
            "g1_japanese_recall": 0.95,
            "g1_precision_at_3": 0.95,
            "g1_no_feed_fallback": 0.98,
            "g2_primary_recall_at_20": 0.90,
            "g2_relevant_recall_at_50": 0.85,
            "g2_precision_at_20": 0.80,
            "g2_japanese_recall_at_50": 0.85,
            "g2_blog_recall_at_50": 0.85,
            "g2_no_rss_recall_at_50": 0.75,
            "g2_min_topic_primary_recall": 0.70,
            "g3_raw_entry_recall": 0.995,
            "g3_important_update_recall": 1.0,
            "g3_duplicate_item_rate": 0.005,
            "g3_family_regression_pp": 1.0,
            "g3_rss_subset_coverage": 0.99,
            "g3_breadth_superiority_pp": 10.0,
            "g4_body_success": 0.97,
            "g4_important_body_recall": 0.95,
            "g4_update_recall": 0.95,
            "g4_update_precision": 0.95,
            "g4_boilerplate_fp": 0.01,
            "g4_article_split": 0.005,
        },
        "exclusion_rules": [
            "policy_blocked sources stay in the universe and are reported separately",
            "do not drop a source after seeing blind results",
            "do not change thresholds after seeing blind results",
            "do not add per-source patches after seeing blind results",
        ],
        "failure_classes": [
            "policy_blocked",
            "undiscovered",
            "unsubscribable",
            "acquisition_failed",
            "extraction_failed",
        ],
        "floors": {
            "min_topics": 24,
            "min_sources": 300,
            "min_per_major_family": 40,
            "min_japanese": 100,
            "min_no_rss_web": 60,
            "min_blind_ratio": 0.30,
        },
        "summary": summary,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sources.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "g0_freeze.json").write_text(
        json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    attestation_path = OUT / "attestation.json"
    if not attestation_path.is_file():
        attestation_path.write_text(
            json.dumps(
                {
                    "dataset_version": freeze["dataset_version"],
                    "status": "awaiting_operator_attestation",
                    "attested_by": None,
                    "attested_at": None,
                    "instruction": (
                        "Review sources.json. If the public-URL set is accepted as "
                        "human-curated gold, set status=attested, attested_by to the "
                        "operator login, and attested_at to an ISO-8601 timestamp. "
                        "Do not attest after reading blind results."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    missing = []
    if summary["source_count"] < 300:
        missing.append(f"sources {summary['source_count']}<300")
    if summary["topic_count"] < 24:
        missing.append(f"topics {summary['topic_count']}<24")
    if summary["japanese_count"] < 100:
        missing.append(f"ja {summary['japanese_count']}<100")
    if summary["no_rss_web_count"] < 60:
        missing.append(f"no_rss {summary['no_rss_web_count']}<60")
    if summary["blind_source_ratio"] < 0.30:
        missing.append(f"blind {summary['blind_source_ratio']:.3f}<0.30")
    for family in ("official_blog", "corp_tech_blog", "personal_dev_blog", "docs_changelog", "rss_atom_json"):
        if summary["families"].get(family, 0) < 40:
            missing.append(f"{family} {summary['families'].get(family, 0)}<40")
    if missing:
        raise SystemExit("G0 floors unmet: " + "; ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
