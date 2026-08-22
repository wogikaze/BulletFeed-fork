package com.bulletfeed.app

object NotificationDemoData {
    val notifications =
        listOf(
            AppNotification(
                id = "notification-next-auth",
                title = "緊急の脆弱性が見つかりました",
                summary = "niyu/bulletfeed-web の next-auth を4.24.8以上へ更新してください。",
                category = NotificationCategory.SECURITY,
                priority = NotificationPriority.URGENT,
                occurredAt = "5分前",
                targetType = NotificationTargetType.VULNERABILITY,
                targetId = "vuln-next-auth",
            ),
            AppNotification(
                id = "notification-workers-runtime",
                title = "利用中のランタイムに破壊的変更予定",
                summary = "Cloudflare Workersの移行期限と、対象リポジトリへの影響を確認してください。",
                category = NotificationCategory.BREAKING_CHANGE,
                priority = NotificationPriority.HIGH,
                occurredAt = "今日 12:05",
                targetType = NotificationTargetType.EVENT,
                targetId = "workers-runtime",
            ),
            AppNotification(
                id = "notification-kotlin-release",
                title = "Kotlin 2.3.0 RCが公開されました",
                summary = "追跡テーマ Kotlin に新しいリリース候補が追加されました。",
                category = NotificationCategory.RELEASE,
                priority = NotificationPriority.NORMAL,
                occurredAt = "今日 09:25",
                targetType = NotificationTargetType.EVENT,
                targetId = "kotlin-release",
                read = true,
            ),
        )
}
