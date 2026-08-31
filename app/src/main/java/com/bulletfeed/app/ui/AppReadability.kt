package com.bulletfeed.app

/** Font-scale and touch-target floors for feed surfaces. Does not claim M4 PASS. */
object AppReadability {
    const val LARGE_FONT_SCALE = 1.3f
    const val MIN_TOUCH_TARGET_DP = 48

    fun titleMaxLines(fontScale: Float): Int = if (fontScale >= LARGE_FONT_SCALE) 4 else 2

    fun summaryMaxLines(fontScale: Float): Int = if (fontScale >= LARGE_FONT_SCALE) 6 else 3
}
