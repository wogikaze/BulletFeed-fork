package com.bulletfeed.app

interface BulletFeedRepository :
    FeedRepository,
    EventRepository,
    MeRepository,
    IntegrationRepository {
    suspend fun initialize()

    suspend fun getFeedEvents(): List<FeedEvent>

    suspend fun getGithubConnection(): Boolean

    suspend fun getOnboardingSnapshot(): OnboardingSnapshot

    suspend fun updateTopics(topics: List<String>): List<String>

    suspend fun updateEventFeedback(
        eventId: String,
        feedback: Feedback,
    ): FeedEvent

    suspend fun setGithubConnected(connected: Boolean): Boolean
}
