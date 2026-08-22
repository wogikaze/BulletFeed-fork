package com.bulletfeed.app

fun FeedEvent.toFeedItem(): FeedItem {
    val deltaType =
        when (importance) {
            Importance.CRITICAL, Importance.HIGH -> DeltaType.STATE_UPDATE
            Importance.MEDIUM -> DeltaType.NEW_FACT
            Importance.LOW -> DeltaType.DETAIL
        }
    return FeedItem(
        id = "fi_$id",
        eventId = id,
        delta =
            FeedDelta(
                id = "delta_$id",
                type = deltaType,
                summary = summary,
                before = before,
                after = after,
                occurredAt = announcedAt,
            ),
        title = title,
        importance =
            ImportanceInfo(
                level = importance,
                reason = importanceReason,
                confidence = "high",
            ),
        relation =
            RelationInfo(
                level = relation,
                reason = relationReason,
                matchedTopics = emptyList(),
                matchedRepositories = emptyList(),
            ),
        status = if (read) FeedItemStatus.READ else FeedItemStatus.UNREAD,
        following = following,
        updatedAt = announcedAt,
        deliveryId = "dlv_$id",
        markedImportant = markedImportant,
        dismissed = dismissed,
    )
}

fun FeedItem.toFeedEvent(base: FeedEvent? = null): FeedEvent {
    val source = base ?: FeedEvent(
        id = eventId,
        title = title,
        summary = delta.summary,
        importance = importance.level,
        importanceReason = importance.reason,
        relation = relation.level,
        relationReason = relation.reason,
        announcedAt = updatedAt,
        sourceCount = 0,
        before = delta.before,
        after = delta.after,
        explicitImpact = delta.summary,
        inferredImpact = null,
        sources = emptyList(),
        timeline = emptyList(),
    )
    return source.copy(
        read = status == FeedItemStatus.READ,
        dismissed = dismissed,
        following = following,
        markedImportant = markedImportant,
        feedItemId = id,
        before = delta.before,
        after = delta.after,
    )
}

fun EventDetail.toFeedEvent(base: FeedEvent? = null): FeedEvent {
    val explicit = impacts.firstOrNull { it.kind == "explicit" }?.text ?: latestDelta.summary
    val inferred = impacts.firstOrNull { it.kind == "inferred" }?.text
    val source = base ?: FeedEvent(
        id = id,
        title = title,
        summary = summary,
        importance = Importance.MEDIUM,
        importanceReason = currentState.summary,
        relation = Relation.REFERENCE,
        relationReason = "",
        announcedAt = currentState.since,
        sourceCount = sources.size,
        before = latestDelta.before,
        after = latestDelta.after,
        explicitImpact = explicit,
        inferredImpact = inferred,
        sources = sources.map { Source(it.publisher, it.title, it.evidence) },
        timeline = timeline.map { TimelineItem(it.occurredAt, it.title, it.description) },
    )
    return source.copy(
        following = following,
        before = (openedDelta ?: latestDelta).before,
        after = (openedDelta ?: latestDelta).after,
        sources = sources.map { Source(it.publisher, it.title, it.evidence) },
        timeline = timeline.map { TimelineItem(it.occurredAt, it.title, it.description) },
        explicitImpact = explicit,
        inferredImpact = inferred,
    )
}
