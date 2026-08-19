package com.bulletfeed.app

import androidx.compose.ui.graphics.Color

enum class Importance(
    val label: String,
    val color: Color,
) {
    CRITICAL("緊急", Color(0xFFB3261E)),
    HIGH("重要", Color(0xFFC65D00)),
    MEDIUM("注目", Color(0xFF365EAA)),
    LOW("参考", Color(0xFF5F6368)),
}

enum class Relation(
    val label: String,
    val color: Color,
) {
    DIRECT("直接影響", Color(0xFF7B3FB5)),
    ADJACENT("近接影響", Color(0xFF1769AA)),
    REFERENCE("参考情報", Color(0xFF5F6368)),
}

enum class Feedback { IMPORTANT, NOT_RELEVANT, READ }

enum class FeedFilter(
    val label: String,
) {
    ALL("すべて"),
    DIRECT("直接影響"),
    ADJACENT("近接影響"),
    REFERENCE("参考"),
}

enum class AppTab(
    val label: String,
    val symbol: String,
) {
    FEED("フィード", "●"),
    SEARCH("検索", "⌕"),
    TOPICS("テーマ", "◎"),
    SETTINGS("設定", "◌"),
}

data class FeedEvent(
    val id: String,
    val title: String,
    val summary: String,
    val importance: Importance,
    val importanceReason: String,
    val relation: Relation,
    val relationReason: String,
    val announcedAt: String,
    val sourceCount: Int,
    val before: String,
    val after: String,
    val explicitImpact: String,
    val inferredImpact: String?,
    val sources: List<Source>,
    val timeline: List<TimelineItem>,
    val read: Boolean = false,
    val dismissed: Boolean = false,
    val following: Boolean = false,
    val markedImportant: Boolean = false,
)

data class Source(
    val publisher: String,
    val title: String,
    val evidence: String,
)

data class TimelineItem(
    val date: String,
    val title: String,
    val description: String,
)
