package com.bulletfeed.app

import kotlinx.coroutines.delay

class MockBulletFeedRepository(
    private val state: MockAppState = MockAppState(),
    private val feedStore: MockFeedStore = MockFeedStore(state),
    private val eventStore: MockEventStore = MockEventStore(state),
    private val meStore: MockMeStore = MockMeStore(state),
    private val integrationStore: MockIntegrationStore = MockIntegrationStore(state),
    private val discoverSiteFeedsOverride: (suspend (String) -> SiteFeedDiscoverResult)? = null,
) : BulletFeedRepository,
    FeedRepository by feedStore,
    EventRepository by eventStore,
    MeRepository by meStore,
    IntegrationRepository by integrationStore {
    override suspend fun initialize() {}

    override suspend fun recoverSession(): Boolean = true

    override suspend fun getFeedEvents(): List<FeedEvent> {
        simulateNetworkDelay()
        return feedStore.getFeedEvents()
    }

    override suspend fun getVulnerabilityAlerts(): List<VulnerabilityAlert> = integrationStore.getVulnerabilityAlerts()

    override suspend fun getNotifications(): List<AppNotification> = integrationStore.getNotifications()

    override suspend fun getGithubConnection(): Boolean = integrationStore.getGithubConnectionState().connected

    override suspend fun getOnboardingSnapshot() =
        OnboardingSnapshot(
            completed = state.onboardingCompleted,
            state = if (state.onboardingCompleted) OnboardingState.READY else OnboardingState.PROFILE,
            profile = state.profile,
            topics = state.topicNames(),
        )

    override suspend fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ): OnboardingSnapshot = meStore.completeOnboarding(profile, topics, connectGithub)

    override suspend fun updateTopics(topics: List<String>): List<String> {
        state.topics =
            topics
                .distinct()
                .mapIndexed { index, name ->
                    UserTopic("topic_$index", name, TopicType.TECHNOLOGY, TopicPriority.NORMAL, index)
                }.toMutableList()
        return state.topicNames()
    }

    override suspend fun updateEventFeedback(
        eventId: String,
        feedback: Feedback,
    ) {
        feedStore.updateByEventId(eventId, feedback)
    }

    override suspend fun setFollowing(
        eventId: String,
        following: Boolean,
    ): FeedEvent = eventStore.setFollowing(eventId, following)

    override suspend fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ): VulnerabilityAlert = integrationStore.updateVulnerabilityStatus(alertId, status)

    override suspend fun markNotificationRead(notificationId: String): AppNotification =
        integrationStore.markNotificationRead(notificationId)

    override suspend fun markAllNotificationsRead(): List<AppNotification> = integrationStore.markAllNotificationsRead()

    override suspend fun setGithubConnected(connected: Boolean): Boolean = integrationStore.setGithubConnected(connected)

    override suspend fun discoverSiteFeeds(url: String): SiteFeedDiscoverResult =
        discoverSiteFeedsOverride?.invoke(url) ?: meStore.discoverSiteFeeds(url)

    private suspend fun simulateNetworkDelay() {
        delay(250)
    }
}
