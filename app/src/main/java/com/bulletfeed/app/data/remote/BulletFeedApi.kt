package com.bulletfeed.app

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

interface BulletFeedApi {
    @POST("v1/sessions")
    suspend fun createSession(): SessionResponseDto

    @GET("v1/feed")
    suspend fun getFeed(
        @Query("relation") relation: String? = null,
        @Query("status") status: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int = 20,
    ): FeedPageDto

    @PUT("v1/feed/items/{feedItemId}/read")
    suspend fun markFeedItemRead(
        @Path("feedItemId") feedItemId: String,
    ): ReadResponseDto

    @POST("v1/feed/items/{feedItemId}/feedback")
    suspend fun sendFeedFeedback(
        @Path("feedItemId") feedItemId: String,
        @Body body: FeedbackDto,
    ): FeedFeedbackResponseDto

    @POST("v1/feed/exposures")
    suspend fun recordExposures(
        @Body body: ExposuresDto,
    ): AcceptedDto

    @GET("v1/events/{eventId}")
    suspend fun getEvent(
        @Path("eventId") eventId: String,
        @Query("fromFeedItem") fromFeedItem: String? = null,
    ): EventDetailDto

    @PUT("v1/events/{eventId}/following")
    suspend fun setFollowing(
        @Path("eventId") eventId: String,
        @Body body: FollowingDto,
    ): FollowingDto

    @GET("v1/me")
    suspend fun getMe(): MeDto

    @GET("v1/me/profile")
    suspend fun getProfile(): ProfileDto

    @PUT("v1/me/profile")
    suspend fun updateProfile(
        @Body body: ProfileDto,
    ): ProfileDto

    @GET("v1/me/topics")
    suspend fun getTopics(): TopicListDto

    @POST("v1/me/topics")
    suspend fun addTopic(
        @Body body: TopicCreateDto,
    ): TopicDto

    @DELETE("v1/me/topics/{topicId}")
    suspend fun deleteTopic(
        @Path("topicId") topicId: String,
    )

    @PATCH("v1/me/topics/{topicId}")
    suspend fun patchTopic(
        @Path("topicId") topicId: String,
        @Body body: TopicPatchDto,
    ): TopicDto

    @GET("v1/topics/search")
    suspend fun searchTopics(
        @Query("q") query: String,
    ): TopicListDto

    @PUT("v1/me/onboarding")
    suspend fun completeOnboarding(
        @Body body: OnboardingDto,
    ): OnboardingResultDto

    @GET("v1/me/integrations/github")
    suspend fun getGithubConnection(): GithubConnectionDto

    @POST("v1/me/integrations/github/authorize")
    suspend fun authorizeGithub(): GithubAuthorizeDto

    @GET("v1/me/integrations/github/repositories")
    suspend fun listGithubRepositories(
        @Query("q") query: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int = 20,
    ): GithubRepositoryPageDto

    @PUT("v1/me/integrations/github/repositories")
    suspend fun updateGithubRepositories(
        @Body body: GithubRepositoryUpdateDto,
    ): GithubConnectionDto

    @DELETE("v1/me/integrations/github")
    suspend fun disconnectGithub()

    @POST("v1/me/integrations/github/import")
    suspend fun importRepositoryKeywords(
        @Body body: GithubRepoImportDto,
    ): GithubImportResultDto

    @GET("v1/me/security/alerts")
    suspend fun getSecurityAlerts(
        @Query("status") status: String? = null,
        @Query("repositoryId") repositoryId: String? = null,
    ): SecurityAlertListDto

    @GET("v1/me/security/alerts/{alertId}")
    suspend fun getSecurityAlert(
        @Path("alertId") alertId: String,
    ): SecurityAlertDto

    @PATCH("v1/me/security/alerts/{alertId}")
    suspend fun patchSecurityAlert(
        @Path("alertId") alertId: String,
        @Body body: SecurityAlertPatchDto,
    ): SecurityAlertDto

    @GET("v1/me/notifications")
    suspend fun getNotifications(
        @Query("status") status: String? = null,
    ): NotificationListDto

    @PATCH("v1/me/notifications/{notificationId}")
    suspend fun patchNotification(
        @Path("notificationId") notificationId: String,
        @Body body: NotificationReadDto,
    ): NotificationDto

    @POST("v1/me/notifications/read-all")
    suspend fun readAllNotifications(): NotificationReadAllDto
}

@Serializable
data class FeedPageDto(
    val items: List<FeedItemDto>,
    val nextCursor: String? = null,
)

@Serializable
data class FeedItemDto(
    val id: String,
    val eventId: String,
    val delta: FeedDeltaDto,
    val title: String,
    val importance: ImportanceDto,
    val relation: RelationDto,
    val status: String,
    val following: Boolean,
    val updatedAt: String,
    val deliveryId: String,
)

@Serializable
data class FeedDeltaDto(
    val id: String,
    val type: String,
    val summary: String,
    val before: String,
    val after: String,
    val occurredAt: String,
)

@Serializable
data class ImportanceDto(
    val level: String,
    val reason: String,
    val confidence: String,
)

@Serializable
data class RelationDto(
    val level: String,
    val reason: String,
    val matchedTopics: List<String>,
    val matchedRepositories: List<MatchedRepositoryDto>,
)

@Serializable
data class MatchedRepositoryDto(
    val id: String,
    val name: String,
    val url: String,
)

@Serializable
data class FeedFeedbackRequestDto(
    val type: String,
)

@Serializable
data class FeedFeedbackResponseDto(
    val feedItemId: String,
    val type: String,
    val status: String,
)

@Serializable
data class ReadResponseDto(
    val feedItemId: String,
    val status: String,
)

@Serializable
data class FeedbackDto(
    val type: String,
)

@Serializable
data class ExposuresDto(
    val items: List<ExposureDto>,
)

@Serializable
data class ExposureDto(
    val deliveryId: String,
    val displayedAt: String,
)

@Serializable
data class AcceptedDto(
    val accepted: Int,
)

@Serializable
data class EventDetailDto(
    val id: String,
    val title: String,
    val summary: String,
    val currentState: CurrentStateDto,
    val latestDelta: FeedDeltaDto,
    val openedDelta: FeedDeltaDto? = null,
    val timeline: List<EventTimelineEntryDto>,
    val impacts: List<EventImpactDto>,
    val sources: List<EventSourceDto>,
    val following: Boolean,
)

@Serializable
data class CurrentStateDto(
    val phase: String,
    val summary: String,
    val since: String,
    val confidence: String,
)

@Serializable
data class EventTimelineEntryDto(
    val id: String,
    val type: String,
    val occurredAt: String,
    val title: String,
    val description: String,
    val deltaId: String? = null,
    val state: Map<String, String>? = null,
)

@Serializable
data class EventImpactDto(
    val kind: String,
    val text: String,
    val confidence: String,
)

@Serializable
data class EventSourceDto(
    val publisher: String,
    val kind: String,
    val title: String,
    val url: String,
    val publishedAt: String,
    val retrievedAt: String,
    val evidence: String,
)

@Serializable
data class FollowingDto(
    val eventId: String? = null,
    val following: Boolean,
)

@Serializable
data class MeDto(
    val onboardingCompleted: Boolean,
    val profile: ProfileDto,
    val topicCount: Int,
    val githubConnected: Boolean,
)

@Serializable
data class ProfileDto(
    val occupation: String,
    val interests: List<String>,
    val region: String,
)

@Serializable
data class TopicListDto(
    val items: List<TopicDto>,
)

@Serializable
data class TopicDto(
    val id: String,
    val name: String,
    val type: String,
    val priority: String,
    val order: Int,
    val createdAt: String,
)

@Serializable
data class TopicCreateDto(
    val name: String,
    val type: String,
)

@Serializable
data class TopicPatchDto(
    val priority: String? = null,
    val order: Int? = null,
)

@Serializable
data class OnboardingDto(
    val profile: ProfileDto,
    val topics: List<String>,
    val connectGithub: Boolean,
)

@Serializable
data class OnboardingResultDto(
    val completed: Boolean,
    val githubAuthorization: GithubAuthorizationDto? = null,
)

@Serializable
data class GithubAuthorizationDto(
    val required: Boolean,
    val authorizationUrl: String? = null,
)

@Serializable
data class GithubConnectionDto(
    val connected: Boolean,
    val accountLogin: String? = null,
)

@Serializable
data class GithubAuthorizeDto(
    val authorizationUrl: String,
    val flowId: String,
    val pollToken: String,
    val expiresInSeconds: Int,
)

@Serializable
data class GithubRepositoryPageDto(
    val items: List<GithubRepositoryDto>,
    val nextCursor: String? = null,
)

@Serializable
data class GithubRepositoryDto(
    val id: String,
    val fullName: String,
    val htmlUrl: String,
    val private: Boolean,
    val description: String? = null,
    val language: String? = null,
    val selected: Boolean,
    val updatedAt: String,
)

@Serializable
data class GithubRepositoryUpdateDto(
    val repositoryIds: List<String>,
)

@Serializable
data class GithubRepoImportDto(
    val fullName: String,
)

@Serializable
data class GithubImportResultDto(
    val fullName: String,
    val keywords: List<String>,
    val addedTopics: List<String>,
)

@Serializable
data class SecurityAlertListDto(
    val items: List<SecurityAlertDto>,
)

@Serializable
data class SecurityAlertDto(
    val id: String,
    val advisoryId: String,
    val cve: String? = null,
    val title: String,
    val summary: String,
    val severity: String,
    val status: String,
    val repository: SecurityAlertRepositoryDto,
    @SerialName("package")
    val packageInfo: SecurityAlertPackageDto,
    val source: String,
    val detectedAt: String,
    val evidence: String,
    val recommendation: String,
    val cvssScore: Double? = null,
)

@Serializable
data class SecurityAlertRepositoryDto(
    val id: String,
    val fullName: String,
)

@Serializable
data class SecurityAlertPackageDto(
    val name: String,
    val currentVersion: String,
    val fixedVersion: String,
    val dependencyType: String,
)

@Serializable
data class SecurityAlertPatchDto(
    val status: String,
)

@Serializable
data class NotificationListDto(
    val items: List<NotificationDto>,
)

@Serializable
data class NotificationDto(
    val id: String,
    val title: String,
    val summary: String,
    val category: String,
    val priority: String,
    val occurredAt: String,
    val read: Boolean,
    val target: NotificationTargetDto,
)

@Serializable
data class NotificationTargetDto(
    val type: String,
    val id: String,
)

@Serializable
data class NotificationReadDto(
    val read: Boolean = true,
)

@Serializable
data class NotificationReadAllDto(
    val updatedCount: Int,
)

@Serializable
data class SessionResponseDto(
    val accessToken: String,
    val userId: String,
)
