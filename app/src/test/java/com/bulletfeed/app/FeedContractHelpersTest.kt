package com.bulletfeed.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FeedContractHelpersTest {
    @Test
    fun `feed filters map to backend relation values`() {
        assertNull(FeedFilter.ALL.toRelationOrNull())
        assertEquals(Relation.DIRECT, FeedFilter.DIRECT.toRelationOrNull())
        assertEquals(Relation.ADJACENT, FeedFilter.ADJACENT.toRelationOrNull())
        assertEquals(Relation.REFERENCE, FeedFilter.REFERENCE.toRelationOrNull())
    }

    @Test
    fun `delivery map is keyed by feed item id`() {
        val page = FeedPage(
            items = listOf(feedItem("feed-1", "event-1", "delivery-1")),
            nextCursor = null,
        )

        assertEquals(mapOf("feed-1" to "delivery-1"), page.deliveryIdMap())
    }

    private fun feedItem(
        id: String,
        eventId: String,
        deliveryId: String,
    ) = FeedItem(
        id = id,
        eventId = eventId,
        delta = FeedDelta(
            id = "delta-1",
            type = DeltaType.NEW_FACT,
            summary = "summary",
            before = "before",
            after = "after",
            occurredAt = "2026-08-23T00:00:00Z",
        ),
        title = "title",
        importance = ImportanceInfo(
            level = Importance.MEDIUM,
            reason = "reason",
            confidence = "high",
        ),
        relation = RelationInfo(
            level = Relation.REFERENCE,
            reason = "reason",
            matchedTopics = emptyList(),
            matchedRepositories = emptyList(),
        ),
        status = FeedItemStatus.UNREAD,
        following = false,
        updatedAt = "2026-08-23T00:00:00Z",
        deliveryId = deliveryId,
    )
}
