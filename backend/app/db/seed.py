from __future__ import annotations

import json
import sqlite3

TOPIC_CATALOG = [
    ("topic_kotlin", "Kotlin", "technology"),
    ("topic_android", "Android", "technology"),
    ("topic_compose", "Jetpack Compose", "technology"),
    ("topic_workers", "Cloudflare Workers", "service"),
    ("topic_openai", "OpenAI API", "service"),
    ("topic_flutter", "Flutter", "technology"),
    ("topic_github", "GitHub", "service"),
]

EVENTS = [
    (
        "workers-runtime",
        "Cloudflare Workers の Node.js 互換性に破壊的変更予定",
        "旧ランタイム挙動が段階的に廃止され、2026年11月から新しい挙動へ移行します。",
        "identified",
        "移行期限と対象APIが公開され、対応確認が必要な状態です。",
        "2026-08-18T03:00:00Z",
        "high",
        "2026-08-18T04:30:00Z",
    ),
    (
        "kotlin-release",
        "Kotlin 2.3.0 のRCが公開",
        "コンパイラとKotlin Multiplatformの改善を含むリリース候補版です。",
        "monitoring",
        "RCが公開され、正式リリース前の検証が可能な状態です。",
        "2026-08-18T00:20:00Z",
        "high",
        "2026-08-18T00:20:00Z",
    ),
    (
        "openai-pricing",
        "OpenAI API のバッチ処理料金を改定",
        "一部モデルのバッチ処理価格とレート制限が更新されました。",
        "identified",
        "料金とレート制限の改定が発表されています。",
        "2026-08-17T09:40:00Z",
        "high",
        "2026-08-17T09:40:00Z",
    ),
    (
        "android-security",
        "Android セキュリティ速報：WebViewの修正を配信",
        "WebViewに関する脆弱性修正が安定版へ反映されました。",
        "resolved",
        "修正済みWebViewが安定版へ配信されています。",
        "2026-08-17T02:05:00Z",
        "medium",
        "2026-08-17T02:05:00Z",
    ),
]

DELTAS = [
    (
        "delta_workers_identified",
        "workers-runtime",
        "state_update",
        "旧ランタイム挙動の廃止期限と対象APIが公開されました。",
        "Node.js互換性フラグによって旧ランタイム挙動が提供されます。",
        "新しいランタイム挙動へ移行し、旧挙動は2026年11月に廃止予定です。",
        "2026-08-18T03:00:00Z",
    ),
    (
        "delta_kotlin_rc",
        "kotlin-release",
        "new_fact",
        "Kotlin 2.3.0 RC が検証可能になりました。",
        "Kotlin 2.2系が最新の安定版です。",
        "Kotlin 2.3.0 RC が検証可能になりました。",
        "2026-08-18T00:20:00Z",
    ),
    (
        "delta_openai_pricing",
        "openai-pricing",
        "new_fact",
        "一部モデルで料金とレート制限が改定されました。",
        "旧料金体系とレート制限が適用されています。",
        "一部モデルで料金とレート制限が改定されました。",
        "2026-08-17T09:40:00Z",
    ),
    (
        "delta_android_webview",
        "android-security",
        "state_update",
        "修正済みWebViewが安定版へ配信されました。",
        "既知の脆弱性を含むWebViewバージョンが利用可能です。",
        "修正済みWebViewが安定版へ配信されました。",
        "2026-08-17T02:05:00Z",
    ),
]

IMPACTS = [
    (
        "imp_workers_explicit",
        "workers-runtime",
        "explicit",
        "対象APIを利用するアプリケーションは移行確認が必要です。",
        "high",
    ),
    (
        "imp_workers_inferred",
        "workers-runtime",
        "inferred",
        "連携リポジトリの依存関係を更新する必要が生じる可能性があります。",
        "medium",
    ),
    ("imp_kotlin_explicit", "kotlin-release", "explicit", "正式リリース前に互換性を検証できます。", "high"),
    (
        "imp_openai_explicit",
        "openai-pricing",
        "explicit",
        "新規バッチジョブには改定後の料金が適用されます。",
        "high",
    ),
    (
        "imp_openai_inferred",
        "openai-pricing",
        "inferred",
        "AIを利用する機能の月次コストを再試算する価値があります。",
        "medium",
    ),
    ("imp_android_explicit", "android-security", "explicit", "利用者は最新のWebViewへ更新できます。", "high"),
]

SOURCES = [
    (
        "src_workers_blog",
        "workers-runtime",
        "Cloudflare",
        "official_changelog",
        "Node.js compatibility update",
        "https://example.com/cloudflare-workers-compat",
        "2026-08-18T03:00:00Z",
        "2026-08-18T03:05:00Z",
        "対象APIの移行期限は2026年11月1日です。",
    ),
    (
        "src_workers_release",
        "workers-runtime",
        "GitHub Releases",
        "github_release",
        "workers-sdk release notes",
        "https://github.com/cloudflare/workers-sdk/releases",
        "2026-08-18T03:30:00Z",
        "2026-08-18T03:35:00Z",
        "新しい互換性モードの提供を開始しました。",
    ),
    (
        "src_kotlin",
        "kotlin-release",
        "Kotlin Blog",
        "official_changelog",
        "Kotlin 2.3.0 RC is here",
        "https://blog.jetbrains.com/kotlin/",
        "2026-08-18T00:20:00Z",
        "2026-08-18T00:25:00Z",
        "RC版の新機能と互換性に関する案内です。",
    ),
    (
        "src_openai",
        "openai-pricing",
        "OpenAI",
        "official_changelog",
        "API pricing update",
        "https://openai.com/api/pricing",
        "2026-08-17T09:40:00Z",
        "2026-08-17T09:45:00Z",
        "Batch APIの価格表を更新しました。",
    ),
    (
        "src_android",
        "android-security",
        "Android Developers",
        "documentation",
        "Android Security Bulletin",
        "https://source.android.com/docs/security/bulletin",
        "2026-08-17T02:05:00Z",
        "2026-08-17T02:10:00Z",
        "WebViewの修正内容を公開しました。",
    ),
]

TIMELINE = [
    (
        "tl_workers_announced",
        "workers-runtime",
        "delta_workers_identified",
        "announced",
        "2026-08-18T03:00:00Z",
        "変更を公式発表",
        "移行期限と対象APIが公開されました。",
        "investigating",
        "identified",
    ),
    (
        "tl_workers_detail",
        "workers-runtime",
        None,
        "information_added",
        "2026-08-18T03:35:00Z",
        "SDKのリリースノートを更新",
        "互換性モードの利用方法が追加されました。",
        None,
        None,
    ),
    (
        "tl_kotlin_announced",
        "kotlin-release",
        "delta_kotlin_rc",
        "announced",
        "2026-08-18T00:20:00Z",
        "RCを公開",
        "リリース候補版が配布されました。",
        None,
        None,
    ),
    (
        "tl_openai_announced",
        "openai-pricing",
        "delta_openai_pricing",
        "announced",
        "2026-08-17T09:40:00Z",
        "価格表を更新",
        "改定内容を公式に発表しました。",
        None,
        None,
    ),
    (
        "tl_android_resolved",
        "android-security",
        "delta_android_webview",
        "resolved",
        "2026-08-17T02:05:00Z",
        "修正版を配信",
        "安定版チャネルへ展開されました。",
        "monitoring",
        "resolved",
    ),
]

FEED_TEMPLATES = [
    {
        "event_id": "workers-runtime",
        "delta_id": "delta_workers_identified",
        "title": "Cloudflare Workers の Node.js 互換性に破壊的変更予定",
        "importance_level": "high",
        "importance_reason": "利用中のAPIに互換性変更と移行期限があるため",
        "importance_confidence": "high",
        "relation_level": "direct",
        "relation_reason": "GitHubで連携したリポジトリが Cloudflare Workers を利用しています。",
        "matched_topics": ["Cloudflare Workers"],
        "matched_repos": [
            {
                "id": "repo_123",
                "name": "niyu/example-worker",
                "url": "https://github.com/niyu/example-worker",
            }
        ],
        "updated_at": "2026-08-18T04:30:00Z",
    },
    {
        "event_id": "kotlin-release",
        "delta_id": "delta_kotlin_rc",
        "title": "Kotlin 2.3.0 のRCが公開",
        "importance_level": "medium",
        "importance_reason": "登録テーマ Kotlin に新しいリリース候補が出たため",
        "importance_confidence": "high",
        "relation_level": "direct",
        "relation_reason": "追跡テーマとして Kotlin を登録しています。",
        "matched_topics": ["Kotlin"],
        "matched_repos": [],
        "updated_at": "2026-08-18T00:20:00Z",
    },
    {
        "event_id": "openai-pricing",
        "delta_id": "delta_openai_pricing",
        "title": "OpenAI API のバッチ処理料金を改定",
        "importance_level": "high",
        "importance_reason": "登録サービスの料金体系が変わり、運用コストに影響しうるため",
        "importance_confidence": "high",
        "relation_level": "adjacent",
        "relation_reason": "AIを興味分野に設定し、OpenAI APIを追跡しています。",
        "matched_topics": ["OpenAI API"],
        "matched_repos": [],
        "updated_at": "2026-08-17T09:40:00Z",
    },
    {
        "event_id": "android-security",
        "delta_id": "delta_android_webview",
        "title": "Android セキュリティ速報：WebViewの修正を配信",
        "importance_level": "low",
        "importance_reason": "Android開発に関連するセキュリティ更新のため",
        "importance_confidence": "medium",
        "relation_level": "reference",
        "relation_reason": "職種を Androidエンジニア と設定しています。",
        "matched_topics": ["Android"],
        "matched_repos": [],
        "updated_at": "2026-08-17T02:05:00Z",
    },
]

SECURITY_ALERTS = [
    {
        "id": "vuln-next-auth",
        "advisory_id": "GHSA-demo-4v6x",
        "cve": "CVE-2026-10421",
        "title": "認証バイパスにつながる可能性のある脆弱性",
        "summary": "特定のセッション構成で認証確認を迂回できる可能性があります。",
        "severity": "critical",
        "status": "open",
        "repository_id": "repo_web",
        "repository_full_name": "niyu/bulletfeed-web",
        "package_name": "next-auth",
        "current_version": "4.22.0",
        "fixed_version": "4.24.8",
        "dependency_type": "direct",
        "detected_at": "2026-08-18T04:10:00Z",
        "source": "GitHub Advisory Database · OSV",
        "evidence": "GitHubの依存関係情報で、影響範囲に含まれるバージョンの直接利用を確認しました。",
        "recommendation": "next-authを4.24.8以上へ更新し、セッション設定を再確認してください。",
        "cvss_score": 9.1,
    },
    {
        "id": "vuln-undici",
        "advisory_id": "GHSA-demo-6m8p",
        "cve": "CVE-2026-09812",
        "title": "不正なリダイレクト処理による情報漏えい",
        "summary": "細工されたリダイレクトによって認証ヘッダーが意図しない宛先へ送信される可能性があります。",
        "severity": "high",
        "status": "in_progress",
        "repository_id": "repo_worker",
        "repository_full_name": "niyu/worker-api",
        "package_name": "undici",
        "current_version": "6.18.1",
        "fixed_version": "6.19.8",
        "dependency_type": "transitive",
        "detected_at": "2026-08-17T11:45:00Z",
        "source": "OSV",
        "evidence": "ロックファイル上の間接依存バージョンが公開された影響範囲と一致しました。",
        "recommendation": "親パッケージを更新し、undici 6.19.8以上が解決されることを確認してください。",
        "cvss_score": 7.5,
    },
    {
        "id": "vuln-compose-preview",
        "advisory_id": "OSV-DEMO-2026-31",
        "cve": None,
        "title": "開発用プレビュー機能の入力検証不足",
        "summary": "開発環境でのみ利用される処理に入力検証の不足がありました。",
        "severity": "medium",
        "status": "resolved",
        "repository_id": "repo_app",
        "repository_full_name": "niyu/BulletFeed",
        "package_name": "demo-preview-tool",
        "current_version": "1.3.0",
        "fixed_version": "1.3.2",
        "dependency_type": "direct",
        "detected_at": "2026-08-16T00:30:00Z",
        "source": "OSV",
        "evidence": "開発用依存関係で一致しました。本番APKには含まれません。",
        "recommendation": "1.3.2へ更新済みです。追加対応はありません。",
        "cvss_score": 5.3,
    },
]

NOTIFICATIONS = [
    {
        "id": "notification-next-auth",
        "title": "緊急の脆弱性が見つかりました",
        "summary": "niyu/bulletfeed-web の next-auth を4.24.8以上へ更新してください。",
        "category": "security",
        "priority": "urgent",
        "occurred_at": "2026-08-18T04:15:00Z",
        "target_type": "vulnerability",
        "target_id": "vuln-next-auth",
        "read": 0,
    },
    {
        "id": "notification-workers-runtime",
        "title": "利用中のランタイムに破壊的変更予定",
        "summary": "Cloudflare Workersの移行期限と、対象リポジトリへの影響を確認してください。",
        "category": "breaking_change",
        "priority": "high",
        "occurred_at": "2026-08-18T03:05:00Z",
        "target_type": "event",
        "target_id": "workers-runtime",
        "read": 0,
    },
    {
        "id": "notification-kotlin-release",
        "title": "Kotlin 2.3.0 RCが公開されました",
        "summary": "追跡テーマ Kotlin に新しいリリース候補が追加されました。",
        "category": "release",
        "priority": "normal",
        "occurred_at": "2026-08-18T00:25:00Z",
        "target_type": "event",
        "target_id": "kotlin-release",
        "read": 1,
    },
]

DEMO_REPOSITORIES = [
    {
        "id": "repo_123",
        "full_name": "niyu/example-worker",
        "html_url": "https://github.com/niyu/example-worker",
        "private": False,
        "description": "Cloudflare Workers example",
        "language": "TypeScript",
        "updated_at": "2026-08-18T01:00:00Z",
    },
    {
        "id": "repo_web",
        "full_name": "niyu/bulletfeed-web",
        "html_url": "https://github.com/niyu/bulletfeed-web",
        "private": True,
        "description": "Web companion",
        "language": "TypeScript",
        "updated_at": "2026-08-17T08:00:00Z",
    },
    {
        "id": "repo_worker",
        "full_name": "niyu/worker-api",
        "html_url": "https://github.com/niyu/worker-api",
        "private": False,
        "description": "Worker API",
        "language": "JavaScript",
        "updated_at": "2026-08-16T12:00:00Z",
    },
    {
        "id": "repo_app",
        "full_name": "niyu/BulletFeed",
        "html_url": "https://github.com/niyu/BulletFeed",
        "private": False,
        "description": "Android app",
        "language": "Kotlin",
        "updated_at": "2026-08-18T02:00:00Z",
    },
]


def seed_catalog(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT OR IGNORE INTO topic_catalog (id, name, type) VALUES (?, ?, ?)",
        TOPIC_CATALOG,
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO events (
            id, title, summary, current_phase, current_summary, current_since,
            current_confidence, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        EVENTS,
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO deltas (
            id, event_id, type, summary, before_text, after_text, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        DELTAS,
    )
    connection.executemany(
        "INSERT OR IGNORE INTO event_impacts (id, event_id, kind, text, confidence) VALUES (?, ?, ?, ?, ?)",
        IMPACTS,
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO event_sources (
            id, event_id, publisher, kind, title, url, published_at, retrieved_at, evidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        SOURCES,
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO event_timeline (
            id, event_id, delta_id, type, occurred_at, title, description, state_before, state_after
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        TIMELINE,
    )


def seed_user_workspace(connection: sqlite3.Connection, user_id: str) -> None:
    for template in FEED_TEMPLATES:
        feed_item_id = f"fi_{user_id}_{template['delta_id']}"
        connection.execute(
            """
            INSERT OR IGNORE INTO feed_items (
                id, user_id, event_id, delta_id, title, importance_level, importance_reason,
                importance_confidence, relation_level, relation_reason, matched_topics_json,
                matched_repos_json, status, dismissed, marked_important, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unread', 0, 0, ?)
            """,
            (
                feed_item_id,
                user_id,
                template["event_id"],
                template["delta_id"],
                template["title"],
                template["importance_level"],
                template["importance_reason"],
                template["importance_confidence"],
                template["relation_level"],
                template["relation_reason"],
                json.dumps(template["matched_topics"]),
                json.dumps(template["matched_repos"]),
                template["updated_at"],
            ),
        )
    for alert in SECURITY_ALERTS:
        connection.execute(
            """
            INSERT OR IGNORE INTO security_alerts (
                id, user_id, advisory_id, cve, title, summary, severity, status,
                repository_id, repository_full_name, package_name, current_version,
                fixed_version, dependency_type, detected_at, source, evidence,
                recommendation, cvss_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert["id"],
                user_id,
                alert["advisory_id"],
                alert["cve"],
                alert["title"],
                alert["summary"],
                alert["severity"],
                alert["status"],
                alert["repository_id"],
                alert["repository_full_name"],
                alert["package_name"],
                alert["current_version"],
                alert["fixed_version"],
                alert["dependency_type"],
                alert["detected_at"],
                alert["source"],
                alert["evidence"],
                alert["recommendation"],
                alert["cvss_score"],
            ),
        )
    for item in NOTIFICATIONS:
        connection.execute(
            """
            INSERT OR IGNORE INTO notifications (
                id, user_id, title, summary, category, priority, occurred_at,
                target_type, target_id, read
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                user_id,
                item["title"],
                item["summary"],
                item["category"],
                item["priority"],
                item["occurred_at"],
                item["target_type"],
                item["target_id"],
                item["read"],
            ),
        )
