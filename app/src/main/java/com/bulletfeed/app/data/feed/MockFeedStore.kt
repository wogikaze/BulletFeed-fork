package com.bulletfeed.app

class MockFeedStore(
    private val state: MockAppState,
) : FeedRepository {
    override suspend fun getFeedItems(): List<FeedItem> =
        if (state.topics.isEmpty()) {
            emptyList()
        } else {
            state.feedItems.filter { !it.dismissed }
        }

    override suspend fun markFeedItemRead(feedItemId: String) {
        applyFeedback(feedItemId, type = null, markRead = true)
    }

    override suspend fun sendFeedFeedback(
        feedItemId: String,
        type: FeedFeedbackType,
    ) {
        applyFeedback(feedItemId, type, markRead = false)
    }

    override suspend fun resetLearnedRanking(): Long = 1L

    override suspend fun startFeedSession(): FeedSessionTelemetry {
        if (state.activeFeedSessionId != null) {
            return FeedSessionTelemetry(id = state.activeFeedSessionId.orEmpty(), startedAt = 1)
        }
        val id = "fs_mock_${state.feedSessionStarts}"
        state.feedSessionStarts += 1
        state.activeFeedSessionId = id
        return FeedSessionTelemetry(version = "session-telemetry-v1", id = id, startedAt = 1)
    }

    override suspend fun endFeedSession(sessionId: String): FeedSessionTelemetry {
        if (state.activeFeedSessionId == sessionId) {
            state.activeFeedSessionId = null
        }
        return FeedSessionTelemetry(id = sessionId, startedAt = 1, endedAt = 2)
    }

    override suspend fun getFeedSessionMetrics(): FeedSessionMetrics =
        FeedSessionMetrics(
            version = "session-telemetry-v1",
            sessionCount = state.feedSessionStarts,
            displayedCount = state.exposures.size,
        )

    override suspend fun recordExposures(items: List<FeedExposure>) {
        val known = state.feedItems.map { it.deliveryId }.toSet()
        state.exposures += items.filter { it.deliveryId in known && it.deliveryId !in state.exposures.map { e -> e.deliveryId } }
    }

    fun getFeedEvents(): List<FeedEvent> =
        if (state.topics.isEmpty()) {
            emptyList()
        } else {
            state.feedItems
                .filter { !it.dismissed }
                .map { it.toFeedEvent(state.catalog[it.eventId]) }
        }

    fun updateByEventId(
        eventId: String,
        feedback: Feedback,
    ): FeedEvent {
        val item = state.feedItems.first { it.eventId == eventId }
        applyFeedback(
            item.id,
            feedback.toFeedFeedbackType(),
            markRead = feedback == Feedback.READ,
        )
        return requireEvent(item.id)
    }

    private fun applyFeedback(
        feedItemId: String,
        type: FeedFeedbackType?,
        markRead: Boolean,
    ) {
        state.feedItems =
            state.feedItems
                .map { item ->
                    if (item.id != feedItemId) {
                        item
                    } else if (markRead) {
                        item.copy(status = FeedItemStatus.READ)
                    } else {
                        when (type) {
                            FeedFeedbackType.IMPORTANT -> item.copy(markedImportant = !item.markedImportant)
                            FeedFeedbackType.NOT_RELEVANT ->
                                item.copy(dismissed = true, status = FeedItemStatus.READ)
                            FeedFeedbackType.FOLLOW -> item.copy(following = true)
                            FeedFeedbackType.UNDO ->
                                item.copy(markedImportant = false, dismissed = false, following = false)
                            FeedFeedbackType.ALREADY_KNEW,
                            FeedFeedbackType.LEARNED_NOW,
                            FeedFeedbackType.LESS_LIKE_THIS,
                            null,
                            -> item
                        }
                    }
                }.toMutableList()
    }

    private fun requireEvent(feedItemId: String): FeedEvent {
        val item = state.feedItems.first { it.id == feedItemId }
        return item.toFeedEvent(state.catalog[item.eventId])
    }
}
