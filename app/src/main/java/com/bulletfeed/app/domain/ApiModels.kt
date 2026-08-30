package com.bulletfeed.app

enum class FeedItemStatus { UNREAD, READ }

enum class FeedFeedbackType {
    IMPORTANT,
    NOT_RELEVANT,
    FOLLOW,
    ALREADY_KNEW,
    LEARNED_NOW,
    LESS_LIKE_THIS,
    UNDO,
}

enum class DeltaType { NEW_FACT, DETAIL, STATE_UPDATE, CORRECTION, UNRESOLVED_CONTRADICTION }

enum class TimelineType { ANNOUNCED, STATE_CHANGED, INFORMATION_ADDED, CORRECTED, RESOLVED }

enum class SourceKind {
    STATUSPAGE,
    GITHUB_ADVISORY,
    OSV,
    GITHUB_RELEASE,
    GITHUB_SBOM,
    RSS_ATOM,
    JSON_FEED,
    OFFICIAL_CHANGELOG,
    DOCUMENTATION,
}

enum class TopicType { TECHNOLOGY, SERVICE, COMPANY }

const val MAX_TRACKED_TOPICS = 20

enum class TopicPriority { HIGH, NORMAL, LOW }

enum class GithubAuthorizationState { PENDING, CONNECTED, FAILED, EXPIRED }

enum class GithubCredentialState { CONNECTED, REAUTHORIZATION_REQUIRED, DISCONNECTED }

enum class OnboardingState { PROFILE, GITHUB_PENDING, REPOSITORY_PENDING, READY }

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

data class EventSource(
    val publisher: String,
    val kind: SourceKind,
    val title: String,
    val url: String,
    val publishedAt: String,
    val retrievedAt: String,
    val evidence: String,
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
    val sources: List<EventSource> = emptyList(),
    val additionalSources: List<EventSource> = emptyList(),
    val markedImportant: Boolean = false,
    val dismissed: Boolean = false,
)

data class FeedPage(
    val items: List<FeedItem>,
    val nextCursor: String?,
)

data class CurrentState(
    val phase: String,
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
    val dwellMs: Long? = null,
    val visibleRatio: Float? = null,
    val detailOpened: Boolean = false,
)

data class TopicRecommendation(
    val id: String,
    val name: String,
    val type: TopicType,
    val score: Float,
    val reason: String,
    val provenance: String,
    val alreadyFollowed: Boolean,
    val confidence: String,
    val sourceSignals: List<String> = emptyList(),
)

data class TopicRecommendationPage(
    val version: String,
    val items: List<TopicRecommendation>,
    val abstentions: List<TopicRecommendationAbstention> = emptyList(),
    val policyVersion: String,
    val cohort: String,
)

data class TopicRecommendationAbstention(
    val name: String,
    val reason: String,
    val score: Float,
)

data class UserTopic(
    val id: String,
    val name: String,
    val type: TopicType,
    val priority: TopicPriority,
    val order: Int,
)

enum class SourceRecommendationStatus { PENDING, APPROVED, IGNORED }

enum class SourceRecommendationDecision { APPROVED, IGNORED }

data class SourcePublisher(
    val slug: String,
    val displayName: String,
)

data class SourceRecommendation(
    val id: String,
    val endpointId: String,
    val canonicalUrl: String,
    val family: String,
    val discoveryMethod: String,
    val discoveryProvenance: String,
    val verificationStatus: String,
    val authorityStatus: String,
    val authorityConfidence: Float,
    val evidenceEligible: Boolean,
    val discoveryOnly: Boolean,
    val reason: String,
    val explanation: String,
    val matchedConcepts: List<String>,
    val matchOrigin: String,
    val matchKind: String,
    val score: Float,
    val recommendationStatus: SourceRecommendationStatus,
    val publisher: SourcePublisher? = null,
)

enum class SourceSubscriptionState { PENDING, OK, FAILING }

enum class UserSourceKind { STATUSPAGE, RSS_ATOM, JSON_FEED }

data class SourceSubscription(
    val id: String,
    val kind: String,
    val canonicalUrl: String,
    val pageId: String? = null,
    val publisher: SourcePublisher? = null,
    val selected: Boolean = true,
    val state: SourceSubscriptionState = SourceSubscriptionState.PENDING,
    val lastSuccessAt: String? = null,
    val lastAttemptAt: String? = null,
    val failureCount: Int = 0,
)

data class MeBootstrap(
    val onboardingCompleted: Boolean,
    val onboardingState: OnboardingState,
    val profile: UserProfile,
    val topicCount: Int,
    val githubConnected: Boolean,
)

data class GithubConnection(
    val connected: Boolean,
    val credentialState: GithubCredentialState = if (connected) GithubCredentialState.CONNECTED else GithubCredentialState.DISCONNECTED,
    val accountLogin: String? = null,
)

data class GithubTopicSyncResult(
    val connection: GithubConnection,
    val addedTopics: List<String> = emptyList(),
    val alreadyTrackedTopics: List<String> = emptyList(),
    val inspectedRepositoryCount: Int = 0,
    val failedRepositoryCount: Int = 0,
)

data class GithubAuthorization(
    val authorizationUrl: String,
    val flowId: String,
    val pollToken: String,
    val expiresInSeconds: Int,
)

data class GithubAuthorizationStatus(
    val state: GithubAuthorizationState,
    val githubLogin: String? = null,
    val detail: String? = null,
)

data class GithubRepositoryChoice(
    val id: String,
    val fullName: String,
    val htmlUrl: String,
    val selected: Boolean,
    val isPrivate: Boolean = false,
    val description: String? = null,
    val language: String? = null,
    val updatedAt: String = "",
)

data class GithubRepositoryPage(
    val items: List<GithubRepositoryChoice>,
    val nextCursor: String?,
)
