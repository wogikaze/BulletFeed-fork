package com.bulletfeed.app

enum class FeedItemStatus { UNREAD, READ }

enum class FeedFeedbackType { IMPORTANT, NOT_RELEVANT }

enum class DeltaType { NEW_FACT, DETAIL, STATE_UPDATE, CORRECTION, UNRESOLVED_CONTRADICTION }

enum class EventPhase { INVESTIGATING, IDENTIFIED, MONITORING, RESOLVED }

enum class TimelineType { ANNOUNCED, STATE_CHANGED, INFORMATION_ADDED, CORRECTED, RESOLVED }

enum class SourceKind {
    STATUSPAGE,
    GITHUB_ADVISORY,
    OSV,
    GITHUB_RELEASE,
    OFFICIAL_CHANGELOG,
    DOCUMENTATION,
}

enum class TopicType { TECHNOLOGY, SERVICE, COMPANY }

enum class TopicPriority { HIGH, NORMAL, LOW }

data class FeedDelta(
    val id: String,
    val type: DeltaType,
    val summary: String,
    val before: String,
    val after: String,
    val occurredAt: String,
)

data class ImportanceInfo(
    val level: Importance,
    val reason: String,
    val confidence: String,
)

data class RelationInfo(
    val level: Relation,
    val reason: String,
    val matchedTopics: List<String>,
    val matchedRepositories: List<MatchedRepository>,
)

data class MatchedRepository(
    val id: String,
    val name: String,
    val url: String,
)

data class FeedItem(
    val id: String,
    val eventId: String,
    val delta: FeedDelta,
    val title: String,
    val importance: ImportanceInfo,
    val relation: RelationInfo,
    val status: FeedItemStatus,
    val following: Boolean,
    val updatedAt: String,
    val deliveryId: String,
    val markedImportant: Boolean = false,
    val dismissed: Boolean = false,
)

data class CurrentState(
    val phase: EventPhase,
    val summary: String,
    val since: String,
    val confidence: String,
)

data class EventTimelineEntry(
    val id: String,
    val type: TimelineType,
    val occurredAt: String,
    val title: String,
    val description: String,
    val deltaId: String?,
    val stateBefore: String?,
    val stateAfter: String?,
)

data class EventImpact(
    val kind: String,
    val text: String,
    val confidence: String,
)

data class EventSource(
    val publisher: String,
    val kind: SourceKind,
    val title: String,
    val url: String,
    val publishedAt: String,
    val retrievedAt: String,
    val evidence: String,
)

data class EventDetail(
    val id: String,
    val title: String,
    val summary: String,
    val currentState: CurrentState,
    val latestDelta: FeedDelta,
    val openedDelta: FeedDelta?,
    val timeline: List<EventTimelineEntry>,
    val impacts: List<EventImpact>,
    val sources: List<EventSource>,
    val following: Boolean,
)

data class FeedExposure(
    val deliveryId: String,
    val displayedAt: String,
)

data class UserTopic(
    val id: String,
    val name: String,
    val type: TopicType,
    val priority: TopicPriority,
    val order: Int,
)

data class MeBootstrap(
    val onboardingCompleted: Boolean,
    val profile: UserProfile,
    val topicCount: Int,
    val githubConnected: Boolean,
)

data class GithubConnection(
    val connected: Boolean,
    val accountLogin: String? = null,
)

data class GithubAuthorization(
    val authorizationUrl: String,
    val flowId: String,
    val pollToken: String,
    val expiresInSeconds: Int,
)

data class GithubRepositoryChoice(
    val id: String,
    val fullName: String,
    val htmlUrl: String,
    val selected: Boolean,
)
