package com.bulletfeed.app

interface BulletFeedRepository {
    suspend fun getFeedEvents(): List<FeedEvent>

    suspend fun getVulnerabilityAlerts(): List<VulnerabilityAlert>

    suspend fun getNotifications(): List<AppNotification>

    suspend fun getGithubConnection(): Boolean

    suspend fun getOnboardingSnapshot(): OnboardingSnapshot

    suspend fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ): OnboardingSnapshot

    suspend fun updateTopics(topics: List<String>): List<String>

    suspend fun updateEventFeedback(
        eventId: String,
        feedback: Feedback,
    ): FeedEvent

    suspend fun setFollowing(
        eventId: String,
        following: Boolean,
    ): FeedEvent

    suspend fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ): VulnerabilityAlert

    suspend fun markNotificationRead(notificationId: String): AppNotification

    suspend fun markAllNotificationsRead(): List<AppNotification>

    suspend fun setGithubConnected(connected: Boolean): Boolean
}
