package com.bulletfeed.app

/**
 * Meaningful viewport display policy (Known-03 / viewport-exposure-v2).
 *
 * Any pixel in the viewport is not enough to record knowledge evidence.
 * This client always sends [dwellMs] and [visibleRatio]. Missing or
 * partial metrics must not become displayed.
 */
object ViewportExposurePolicy {
    const val VERSION = "viewport-exposure-v2"
    const val MIN_DWELL_MS = 1000L
    const val MIN_VISIBLE_RATIO = 0.50f

    fun isMeaningful(
        dwellMs: Long?,
        visibleRatio: Float?,
        detailOpened: Boolean = false,
    ): Boolean {
        if (detailOpened) return true
        if (dwellMs == null || visibleRatio == null) return false
        if (dwellMs < MIN_DWELL_MS) return false
        if (visibleRatio < MIN_VISIBLE_RATIO) return false
        return true
    }
}

data class ViewportItemSnapshot(
    val feedItemId: String,
    val visibleRatio: Float,
)

data class MeaningfulViewportExposure(
    val feedItemId: String,
    val dwellMs: Long,
    val visibleRatio: Float,
    val detailOpened: Boolean = false,
)

fun visibleRatio(
    offset: Int,
    size: Int,
    viewportStart: Int,
    viewportEnd: Int,
): Float {
    if (size <= 0) return 0f
    val visible = minOf(offset + size, viewportEnd) - maxOf(offset, viewportStart)
    return (visible.coerceAtLeast(0).toFloat() / size.toFloat()).coerceIn(0f, 1f)
}

/**
 * Accumulates dwell only while an item stays at or above the visible-fraction
 * threshold. Recomposition/rotation with the same tracker does not restart
 * the clock. Fast-scroll transients never emit.
 */
class ViewportExposureTracker(
    private val nowMs: () -> Long,
    private val minDwellMs: Long = ViewportExposurePolicy.MIN_DWELL_MS,
    private val minVisibleRatio: Float = ViewportExposurePolicy.MIN_VISIBLE_RATIO,
) {
    private data class Watch(
        val firstQualifyingAtMs: Long,
        var maxVisibleRatio: Float,
        var emitted: Boolean = false,
    )

    private val watches = mutableMapOf<String, Watch>()

    fun onSnapshots(
        items: List<ViewportItemSnapshot>,
        atMs: Long = nowMs(),
    ): List<MeaningfulViewportExposure> {
        val present = items.associateBy { it.feedItemId }
        watches.keys.toList().forEach { feedItemId ->
            val snapshot = present[feedItemId]
            val watch = watches[feedItemId] ?: return@forEach
            if ((snapshot == null || snapshot.visibleRatio < minVisibleRatio) && !watch.emitted) {
                watches.remove(feedItemId)
            }
        }
        val ready = mutableListOf<MeaningfulViewportExposure>()
        items.forEach { item ->
            if (item.visibleRatio < minVisibleRatio) return@forEach
            val existing = watches[item.feedItemId]
            if (existing == null) {
                watches[item.feedItemId] =
                    Watch(firstQualifyingAtMs = atMs, maxVisibleRatio = item.visibleRatio)
                return@forEach
            }
            existing.maxVisibleRatio = maxOf(existing.maxVisibleRatio, item.visibleRatio)
            val dwellMs = (atMs - existing.firstQualifyingAtMs).coerceAtLeast(0L)
            if (
                !existing.emitted &&
                ViewportExposurePolicy.isMeaningful(dwellMs, existing.maxVisibleRatio)
            ) {
                existing.emitted = true
                ready +=
                    MeaningfulViewportExposure(
                        feedItemId = item.feedItemId,
                        dwellMs = dwellMs,
                        visibleRatio = existing.maxVisibleRatio,
                    )
            }
        }
        return ready
    }

    fun onDetailOpened(
        feedItemId: String,
        atMs: Long = nowMs(),
    ): MeaningfulViewportExposure {
        val existing = watches[feedItemId]
        val dwellMs = existing?.let { (atMs - it.firstQualifyingAtMs).coerceAtLeast(0L) } ?: 0L
        val ratio = existing?.maxVisibleRatio ?: 1f
        watches[feedItemId] =
            Watch(
                firstQualifyingAtMs = existing?.firstQualifyingAtMs ?: atMs,
                maxVisibleRatio = ratio,
                emitted = true,
            )
        return MeaningfulViewportExposure(
            feedItemId = feedItemId,
            dwellMs = dwellMs,
            visibleRatio = ratio,
            detailOpened = true,
        )
    }

    fun nextDueAtMs(): Long? =
        watches.values
            .filter { !it.emitted }
            .minOfOrNull { it.firstQualifyingAtMs + minDwellMs }

    fun allowRetry(feedItemIds: Collection<String>) {
        feedItemIds.forEach { watches[it]?.emitted = false }
    }

    fun reset() {
        watches.clear()
    }
}
