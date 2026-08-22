package com.bulletfeed.app

import kotlinx.coroutines.delay

class MockBulletFeedRepository : BulletFeedRepository {
    private var events = DemoData.events
    private var alerts = SecurityDemoData.alerts
    private var notifications = NotificationDemoData.notifications
    private var githubConnected = false
    private var onboardingCompleted = false
    private var profile =
        UserProfile(
            role = "Androidエンジニア",
            interests = setOf("モバイル", "AI", "クラウド"),
            region = "東京",
        )
    private var topics = listOf("Kotlin", "Cloudflare Workers", "OpenAI API", "Flutter", "Android")

    override suspend fun getFeedEvents(): List<FeedEvent> {
        simulateNetworkDelay()
        return events
    }

    override suspend fun getVulnerabilityAlerts(): List<VulnerabilityAlert> = alerts

    override suspend fun getNotifications(): List<AppNotification> = notifications

    override suspend fun getGithubConnection(): Boolean = githubConnected

    override suspend fun getOnboardingSnapshot() =
        OnboardingSnapshot(
            completed = onboardingCompleted,
            profile = profile,
            topics = topics,
        )

    override suspend fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ): OnboardingSnapshot {
        this.profile = profile
        this.topics = topics.distinct()
        githubConnected = connectGithub
        onboardingCompleted = true
        return getOnboardingSnapshot()
    }

    override suspend fun updateTopics(topics: List<String>): List<String> {
        this.topics = topics.distinct()
        return this.topics
    }

    override suspend fun updateEventFeedback(
        eventId: String,
        feedback: Feedback,
    ): FeedEvent {
        events =
            events.map { event ->
                if (event.id != eventId) {
                    event
                } else {
                    when (feedback) {
                        Feedback.IMPORTANT -> event.copy(markedImportant = !event.markedImportant)
                        Feedback.NOT_RELEVANT -> event.copy(read = true, dismissed = true)
                        Feedback.READ -> event.copy(read = true)
                    }
                }
            }
        return events.first { it.id == eventId }
    }

    override suspend fun setFollowing(
        eventId: String,
        following: Boolean,
    ): FeedEvent {
        events = events.map { event -> if (event.id == eventId) event.copy(following = following) else event }
        return events.first { it.id == eventId }
    }

    override suspend fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ): VulnerabilityAlert {
        alerts = alerts.map { alert -> if (alert.id == alertId) alert.copy(status = status) else alert }
        return alerts.first { it.id == alertId }
    }

    override suspend fun markNotificationRead(notificationId: String): AppNotification {
        notifications = notifications.map { item -> if (item.id == notificationId) item.copy(read = true) else item }
        return notifications.first { it.id == notificationId }
    }

    override suspend fun markAllNotificationsRead(): List<AppNotification> {
        notifications = notifications.map { it.copy(read = true) }
        return notifications
    }

    override suspend fun setGithubConnected(connected: Boolean): Boolean {
        githubConnected = connected
        return githubConnected
    }

    private suspend fun simulateNetworkDelay() {
        delay(250)
    }
}
