package com.bulletfeed.app

/** Phone vs large-screen chrome. Material3 compact/medium breakpoint is 600dp. */
enum class AppChromeLayout {
    BOTTOM_BAR,
    NAVIGATION_RAIL,
    ;

    companion object {
        const val RAIL_MIN_WIDTH_DP = 600
        const val LIST_DETAIL_MIN_WIDTH_DP = 840

        fun fromWidthDp(widthDp: Int): AppChromeLayout =
            if (widthDp >= RAIL_MIN_WIDTH_DP) NAVIGATION_RAIL else BOTTOM_BAR

        fun usesListDetail(widthDp: Int): Boolean = widthDp >= LIST_DETAIL_MIN_WIDTH_DP

        fun showsEventListDetail(
            widthDp: Int,
            tab: AppTab,
            selectedEventId: String?,
            overlayOpen: Boolean,
        ): Boolean =
            usesListDetail(widthDp) &&
                selectedEventId != null &&
                !overlayOpen &&
                tab in EVENT_LIST_DETAIL_TABS

        fun showsVulnerabilityListDetail(
            widthDp: Int,
            tab: AppTab,
            selectedEventId: String?,
            selectedVulnerabilityId: String?,
            overlayOpen: Boolean,
        ): Boolean =
            usesListDetail(widthDp) &&
                selectedVulnerabilityId != null &&
                selectedEventId == null &&
                !overlayOpen &&
                tab == AppTab.SECURITY
    }
}

private val EVENT_LIST_DETAIL_TABS = setOf(AppTab.FEED, AppTab.SEARCH)
