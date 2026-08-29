package com.bulletfeed.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ViewportExposureTest {
    @Test
    fun policyMatchesBackendViewportExposureV1() {
        assertEquals("viewport-exposure-v1", ViewportExposurePolicy.VERSION)
        assertEquals(1000L, ViewportExposurePolicy.MIN_DWELL_MS)
        assertEquals(0.50f, ViewportExposurePolicy.MIN_VISIBLE_RATIO)
    }

    @Test
    fun missingMetricsCountAsDisplayedForCompat() {
        assertTrue(ViewportExposurePolicy.isMeaningful(null, null))
    }

    @Test
    fun tooBriefOrTinyVisibilityIsNotMeaningful() {
        assertFalse(ViewportExposurePolicy.isMeaningful(200L, 1f))
        assertFalse(ViewportExposurePolicy.isMeaningful(5_000L, 0.05f))
        assertTrue(
            ViewportExposurePolicy.isMeaningful(
                ViewportExposurePolicy.MIN_DWELL_MS,
                ViewportExposurePolicy.MIN_VISIBLE_RATIO,
            ),
        )
        assertTrue(ViewportExposurePolicy.isMeaningful(50L, 0.1f, detailOpened = true))
    }

    @Test
    fun visibleRatioUsesOverlapNotAnyPixel() {
        assertEquals(0.10f, visibleRatio(offset = 90, size = 100, viewportStart = 0, viewportEnd = 100), 0.001f)
        assertEquals(1f, visibleRatio(offset = 0, size = 100, viewportStart = 0, viewportEnd = 200), 0.001f)
        assertEquals(0f, visibleRatio(offset = 200, size = 100, viewportStart = 0, viewportEnd = 100), 0.001f)
    }

    @Test
    fun transientVisibilityDoesNotEmit() {
        val tracker = ViewportExposureTracker(nowMs = { 0L })
        val visible = listOf(ViewportItemSnapshot("feed-1", 0.9f))

        assertTrue(tracker.onSnapshots(visible, atMs = 0L).isEmpty())
        assertTrue(tracker.onSnapshots(visible, atMs = 200L).isEmpty())
        assertTrue(tracker.onSnapshots(emptyList(), atMs = 250L).isEmpty())
        assertTrue(tracker.onSnapshots(visible, atMs = 300L).isEmpty())
    }

    @Test
    fun tinyVisibilityNeverStartsDwell() {
        val tracker = ViewportExposureTracker(nowMs = { 0L })
        val sliver = listOf(ViewportItemSnapshot("feed-1", 0.05f))

        assertTrue(tracker.onSnapshots(sliver, atMs = 0L).isEmpty())
        assertTrue(tracker.onSnapshots(sliver, atMs = 5_000L).isEmpty())
    }

    @Test
    fun sustainedVisibilityEmitsOnce() {
        val tracker = ViewportExposureTracker(nowMs = { 0L })
        val visible = listOf(ViewportItemSnapshot("feed-1", 0.8f))

        assertTrue(tracker.onSnapshots(visible, atMs = 0L).isEmpty())
        val first = tracker.onSnapshots(visible, atMs = 1_000L)
        assertEquals(1, first.size)
        assertEquals("feed-1", first.single().feedItemId)
        assertEquals(1_000L, first.single().dwellMs)
        assertEquals(0.8f, first.single().visibleRatio)
        assertFalse(first.single().detailOpened)

        val repeated = tracker.onSnapshots(visible, atMs = 2_000L)
        assertTrue(repeated.isEmpty())
    }

    @Test
    fun recompositionDoesNotResetDwellOrReemit() {
        val tracker = ViewportExposureTracker(nowMs = { 0L })
        val visible = listOf(ViewportItemSnapshot("feed-1", 0.7f))

        tracker.onSnapshots(visible, atMs = 0L)
        tracker.onSnapshots(visible, atMs = 10L)
        tracker.onSnapshots(visible, atMs = 20L)
        val ready = tracker.onSnapshots(visible, atMs = 1_000L)
        assertEquals(1, ready.size)
        assertEquals(1_000L, ready.single().dwellMs)
        assertTrue(tracker.onSnapshots(visible, atMs = 1_010L).isEmpty())
    }

    @Test
    fun detailOpenCountsImmediately() {
        val tracker = ViewportExposureTracker(nowMs = { 0L })
        val exposure = tracker.onDetailOpened("feed-1", atMs = 40L)

        assertEquals("feed-1", exposure.feedItemId)
        assertTrue(exposure.detailOpened)
        assertEquals(1f, exposure.visibleRatio)
        assertTrue(tracker.onSnapshots(listOf(ViewportItemSnapshot("feed-1", 0.9f)), atMs = 2_000L).isEmpty())
    }

    @Test
    fun failedPostCanRetryAfterAllowRetry() {
        val tracker = ViewportExposureTracker(nowMs = { 0L })
        val visible = listOf(ViewportItemSnapshot("feed-1", 1f))
        tracker.onSnapshots(visible, atMs = 0L)
        assertEquals(1, tracker.onSnapshots(visible, atMs = 1_000L).size)

        tracker.allowRetry(listOf("feed-1"))
        val retried = tracker.onSnapshots(visible, atMs = 1_200L)
        assertEquals(1, retried.size)
        assertEquals(1_200L, retried.single().dwellMs)
    }
}
