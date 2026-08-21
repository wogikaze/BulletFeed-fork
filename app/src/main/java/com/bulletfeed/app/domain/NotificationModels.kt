package com.bulletfeed.app

import androidx.compose.ui.graphics.Color

enum class NotificationCategory(
    val label: String,
    val color: Color,
) {
    SECURITY("セキュリティ", Color(0xFFB42318)),
    BREAKING_CHANGE("重要な変更", Color(0xFFD55A00)),
    RELEASE("リリース", Color(0xFF006A67)),
}

enum class NotificationPriority {
    URGENT,
    HIGH,
    NORMAL,
}

enum class NotificationTargetType {
    EVENT,
    VULNERABILITY,
}

data class AppNotification(
    val id: String,
    val title: String,
    val summary: String,
    val category: NotificationCategory,
    val priority: NotificationPriority,
    val occurredAt: String,
    val targetType: NotificationTargetType,
    val targetId: String,
    val read: Boolean = false,
)

enum class NotificationFilter(
    val label: String,
) {
    UNREAD("未読"),
    ALL("すべて"),
}
