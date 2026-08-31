package com.bulletfeed.app

import androidx.compose.ui.graphics.Color

enum class Importance(
    val label: String,
    val color: Color,
) {
    CRITICAL("緊急", Color(0xFFB42318)),
    HIGH("重要", Color(0xFFD55A00)),
    MEDIUM("注目", Color(0xFF9A6700)),
    LOW("参考", Color(0xFF5F6368)),
}

enum class Relation(
    val label: String,
    val color: Color,
) {
    DIRECT("直接影響", Color(0xFFC62828)),
    ADJACENT("近接影響", Color(0xFFA15C00)),
    REFERENCE("参考情報", Color(0xFF5F6368)),
}

enum class Feedback {
    IMPORTANT,
    NOT_RELEVANT,
    READ,
    FOLLOW,
    ALREADY_KNEW,
    LEARNED_NOW,
    LESS_LIKE_THIS,
    UNDO,
}

fun Feedback.toFeedFeedbackType(): FeedFeedbackType? =
    when (this) {
        Feedback.READ -> null
        Feedback.IMPORTANT -> FeedFeedbackType.IMPORTANT
        Feedback.NOT_RELEVANT -> FeedFeedbackType.NOT_RELEVANT
        Feedback.FOLLOW -> FeedFeedbackType.FOLLOW
        Feedback.ALREADY_KNEW -> FeedFeedbackType.ALREADY_KNEW
        Feedback.LEARNED_NOW -> FeedFeedbackType.LEARNED_NOW
        Feedback.LESS_LIKE_THIS -> FeedFeedbackType.LESS_LIKE_THIS
        Feedback.UNDO -> FeedFeedbackType.UNDO
    }

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
) {
    FEED("フィード"),
    SECURITY("セキュリティ"),
    SEARCH("検索"),
    TOPICS("テーマ"),
    SETTINGS("設定"),
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
    val feedItemId: String = id,
    val displayReason: DisplayReason? = null,
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
