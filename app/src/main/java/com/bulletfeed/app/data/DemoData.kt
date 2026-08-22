package com.bulletfeed.app

object DemoData {
    const val MINIMUM_TOPIC_COUNT = 5
    val defaultTopics =
        listOf(
            "Kotlin",
            "Android",
            "Jetpack Compose",
            "Cloudflare Workers",
            "OpenAI API",
            "GitHub",
            "Flutter",
            "Python",
            "FastAPI",
            "PostgreSQL",
        )

    val events =
        listOf(
            FeedEvent(
                id = "workers-runtime",
                title = "Cloudflare Workers の Node.js 互換性に破壊的変更予定",
                summary = "旧ランタイム挙動が段階的に廃止され、2026年11月から新しい挙動へ移行します。",
                importance = Importance.HIGH,
                importanceReason = "利用中のAPIに互換性変更と移行期限があるため",
                relation = Relation.DIRECT,
                relationReason = "GitHubで連携したリポジトリが Cloudflare Workers を利用しています。",
                announcedAt = "今日 12:00",
                sourceCount = 2,
                before = "Node.js互換性フラグによって旧ランタイム挙動が提供されます。",
                after = "新しいランタイム挙動へ移行し、旧挙動は2026年11月に廃止予定です。",
                explicitImpact = "対象APIを利用するアプリケーションは移行確認が必要です。",
                inferredImpact = "連携リポジトリの依存関係を更新する必要が生じる可能性があります。",
                sources =
                    listOf(
                        Source("Cloudflare", "Node.js compatibility update", "対象APIの移行期限は2026年11月1日です。"),
                        Source("GitHub Releases", "workers-sdk release notes", "新しい互換性モードの提供を開始しました。"),
                    ),
                timeline =
                    listOf(
                        TimelineItem("今日 12:00", "変更を公式発表", "移行期限と対象APIが公開されました。"),
                        TimelineItem("今日 12:35", "SDKのリリースノートを更新", "互換性モードの利用方法が追加されました。"),
                    ),
            ),
            FeedEvent(
                id = "kotlin-release",
                title = "Kotlin 2.3.0 のRCが公開",
                summary = "コンパイラとKotlin Multiplatformの改善を含むリリース候補版です。",
                importance = Importance.MEDIUM,
                importanceReason = "登録テーマ Kotlin に新しいリリース候補が出たため",
                relation = Relation.DIRECT,
                relationReason = "追跡テーマとして Kotlin を登録しています。",
                announcedAt = "今日 09:20",
                sourceCount = 1,
                before = "Kotlin 2.2系が最新の安定版です。",
                after = "Kotlin 2.3.0 RC が検証可能になりました。",
                explicitImpact = "正式リリース前に互換性を検証できます。",
                inferredImpact = null,
                sources = listOf(Source("Kotlin Blog", "Kotlin 2.3.0 RC is here", "RC版の新機能と互換性に関する案内です。")),
                timeline = listOf(TimelineItem("今日 09:20", "RCを公開", "リリース候補版が配布されました。")),
            ),
            FeedEvent(
                id = "openai-pricing",
                title = "OpenAI API のバッチ処理料金を改定",
                summary = "一部モデルのバッチ処理価格とレート制限が更新されました。",
                importance = Importance.HIGH,
                importanceReason = "登録サービスの料金体系が変わり、運用コストに影響しうるため",
                relation = Relation.ADJACENT,
                relationReason = "AIを興味分野に設定し、OpenAI APIを追跡しています。",
                announcedAt = "昨日 18:40",
                sourceCount = 1,
                before = "旧料金体系とレート制限が適用されています。",
                after = "一部モデルで料金とレート制限が改定されました。",
                explicitImpact = "新規バッチジョブには改定後の料金が適用されます。",
                inferredImpact = "AIを利用する機能の月次コストを再試算する価値があります。",
                sources = listOf(Source("OpenAI", "API pricing update", "Batch APIの価格表を更新しました。")),
                timeline = listOf(TimelineItem("昨日 18:40", "価格表を更新", "改定内容を公式に発表しました。")),
            ),
            FeedEvent(
                id = "android-security",
                title = "Android セキュリティ速報：WebViewの修正を配信",
                summary = "WebViewに関する脆弱性修正が安定版へ反映されました。",
                importance = Importance.LOW,
                importanceReason = "Android開発に関連するセキュリティ更新のため",
                relation = Relation.REFERENCE,
                relationReason = "職種を Androidエンジニア と設定しています。",
                announcedAt = "昨日 11:05",
                sourceCount = 2,
                before = "既知の脆弱性を含むWebViewバージョンが利用可能です。",
                after = "修正済みWebViewが安定版へ配信されました。",
                explicitImpact = "利用者は最新のWebViewへ更新できます。",
                inferredImpact = null,
                sources = listOf(Source("Android Developers", "Android Security Bulletin", "WebViewの修正内容を公開しました。")),
                timeline = listOf(TimelineItem("昨日 11:05", "修正版を配信", "安定版チャネルへ展開されました。")),
            ),
        )
}
