package com.bulletfeed.app

class MockFeedStore(
    private val state: MockAppState,
) : FeedRepository {
    override suspend fun getFeedItems(): List<FeedItem> = state.feedItems.filter { !it.dismissed }

    override suspend fun markFeedItemRead(feedItemId: String) {
        applyFeedback(feedItemId, type = null, markRead = true)
    }

    override suspend fun sendFeedFeedback(
        feedItemId: String,
        type: FeedFeedbackType,
    ) {
        applyFeedback(feedItemId, type, markRead = false)
    }

    override suspend fun recordExposures(items: List<FeedExposure>) {
        val known = state.feedItems.map { it.deliveryId }.toSet()
        state.exposures += items.filter { it.deliveryId in known && it.deliveryId !in state.exposures.map { e -> e.deliveryId } }
    }

    fun getFeedEvents(): List<FeedEvent> =
        state.feedItems
            .filter { !it.dismissed }
            .map { it.toFeedEvent(state.catalog[it.eventId]) }

    fun updateByEventId(
        eventId: String,
        feedback: Feedback,
    ): FeedEvent {
        val item = state.feedItems.first { it.eventId == eventId }
        applyFeedback(
            item.id,
            when (feedback) {
                Feedback.READ -> null
                Feedback.IMPORTANT -> FeedFeedbackType.IMPORTANT
                Feedback.NOT_RELEVANT -> FeedFeedbackType.NOT_RELEVANT
            },
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
                            null -> item
                        }
                    }
                }.toMutableList()
    }

    private fun requireEvent(feedItemId: String): FeedEvent {
        val item = state.feedItems.first { it.id == feedItemId }
        return item.toFeedEvent(state.catalog[item.eventId])
    }
}
