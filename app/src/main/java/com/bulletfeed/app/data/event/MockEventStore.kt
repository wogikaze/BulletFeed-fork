package com.bulletfeed.app

class MockEventStore(
    private val state: MockAppState,
) : EventRepository {
    override suspend fun getEventDetail(
        eventId: String,
        fromFeedItemId: String?,
    ): EventDetail {
        val event = state.catalog[eventId] ?: error("Event was not found")
        val feedItem =
            state.feedItems.firstOrNull { item ->
                item.eventId == eventId && (fromFeedItemId == null || item.id == fromFeedItemId)
            } ?: event.toFeedItem()
        val delta = feedItem.delta
        return EventDetail(
            id = event.id,
            title = event.title,
            summary = event.summary,
            currentState =
                CurrentState(
                    phase = "identified",
                    summary = event.summary,
                    since = event.announcedAt,
                    confidence = "high",
                ),
            latestDelta = delta,
            openedDelta = if (fromFeedItemId == null) null else delta,
            unknownFacts =
                buildList {
                    event.summary.trim().takeIf { it.isNotEmpty() }?.let {
                        add(UnknownFact("uf_${event.id}_summary", it))
                    }
                    event.timeline.forEachIndexed { index, item ->
                        val text = item.description.trim().ifEmpty { item.title.trim() }
                        if (text.isNotEmpty()) {
                            add(UnknownFact("uf_${event.id}_$index", text))
                        }
                    }
                }.distinctBy { it.text },
            timeline =
                event.timeline.mapIndexed { index, item ->
                    EventTimelineEntry(
                        id = "tl_${event.id}_$index",
                        type = if (index == 0) TimelineType.ANNOUNCED else TimelineType.INFORMATION_ADDED,
                        occurredAt = item.date,
                        title = item.title,
                        description = item.description,
                        deltaId = delta.id,
                        stateBefore = null,
                        stateAfter = null,
                    )
                },
            impacts =
                listOfNotNull(
                    EventImpact("explicit", event.explicitImpact, "high"),
                    event.inferredImpact?.let { EventImpact("inferred", it, "medium") },
                ),
            sources =
                event.sources.map {
                    EventSource(
                        publisher = it.publisher,
                        kind = SourceKind.OFFICIAL_CHANGELOG,
                        title = it.title,
                        url = "https://example.com",
                        publishedAt = event.announcedAt,
                        retrievedAt = event.announcedAt,
                        evidence = it.evidence,
                    )
                },
            following = state.feedItems.any { it.eventId == eventId && it.following },
        )
    }

    override suspend fun setFollowing(
        eventId: String,
        following: Boolean,
    ): FeedEvent {
        state.feedItems =
            state.feedItems
                .map { item -> if (item.eventId == eventId) item.copy(following = following) else item }
                .toMutableList()
        val item = state.feedItems.first { it.eventId == eventId }
        return item.toFeedEvent(state.catalog[eventId])
    }
}
