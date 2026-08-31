package com.bulletfeed.app

/** Phone vs large-screen chrome. Material3 compact/medium breakpoint is 600dp. */
enum class AppChromeLayout {
    BOTTOM_BAR,
    NAVIGATION_RAIL,
    ;

    companion object {
        const val RAIL_MIN_WIDTH_DP = 600

        fun fromWidthDp(widthDp: Int): AppChromeLayout =
            if (widthDp >= RAIL_MIN_WIDTH_DP) NAVIGATION_RAIL else BOTTOM_BAR
    }
}
