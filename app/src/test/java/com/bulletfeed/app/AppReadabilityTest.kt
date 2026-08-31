package com.bulletfeed.app

import org.junit.Assert.assertEquals
import org.junit.Test

class AppReadabilityTest {
    @Test
    fun defaultFontScaleKeepsCompactLineClamp() {
        assertEquals(2, AppReadability.titleMaxLines(1.0f))
        assertEquals(3, AppReadability.summaryMaxLines(1.0f))
        assertEquals(2, AppReadability.titleMaxLines(1.29f))
    }

    @Test
    fun largeFontScaleRaisesLineClamp() {
        assertEquals(4, AppReadability.titleMaxLines(1.3f))
        assertEquals(6, AppReadability.summaryMaxLines(1.3f))
        assertEquals(4, AppReadability.titleMaxLines(2.0f))
        assertEquals(6, AppReadability.summaryMaxLines(2.0f))
    }

    @Test
    fun minimumTouchTargetMatchesAccessibilityFloor() {
        assertEquals(48, AppReadability.MIN_TOUCH_TARGET_DP)
    }
}
