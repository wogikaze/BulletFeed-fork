package com.bulletfeed.app

interface FeedRepository {
    suspend fun getFeedItems(): List<FeedItem>

    suspend fun markFeedItemRead(feedItemId: String): FeedEvent

    suspend fun sendFeedFeedback(
        feedItemId: String,
        type: FeedFeedbackType,
    ): FeedEvent

    suspend fun recordExposures(items: List<FeedExposure>)
}

interface EventRepository {
    suspend fun getEventDetail(
        eventId: String,
        fromFeedItemId: String? = null,
    ): EventDetail

    suspend fun setFollowing(
        eventId: String,
        following: Boolean,
    ): FeedEvent
}

interface MeRepository {
    suspend fun getMe(): MeBootstrap

    suspend fun getProfile(): UserProfile

    suspend fun saveProfile(profile: UserProfile): UserProfile

    suspend fun getUserTopics(): List<UserTopic>

    suspend fun addUserTopic(
        name: String,
        type: TopicType,
    ): UserTopic

    suspend fun removeUserTopic(topicId: String)

    suspend fun patchUserTopic(
        topicId: String,
        priority: TopicPriority? = null,
        order: Int? = null,
    ): UserTopic

    suspend fun searchTopics(query: String): List<UserTopic>

    suspend fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ): OnboardingSnapshot
}

interface IntegrationRepository {
    suspend fun getGithubConnectionState(): GithubConnection

    suspend fun startGithubAuthorization(): GithubAuthorization

    suspend fun listGithubRepositories(query: String = ""): List<GithubRepositoryChoice>

    suspend fun updateGithubRepositories(repositoryIds: List<String>): GithubConnection

    suspend fun importFromPublicRepo(fullName: String): List<String>

    suspend fun disconnectGithub()

    suspend fun getVulnerabilityAlerts(): List<VulnerabilityAlert>

    suspend fun getVulnerabilityAlert(alertId: String): VulnerabilityAlert

    suspend fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ): VulnerabilityAlert

    suspend fun getNotifications(): List<AppNotification>

    suspend fun markNotificationRead(notificationId: String): AppNotification

    suspend fun markAllNotificationsRead(): List<AppNotification>
}
