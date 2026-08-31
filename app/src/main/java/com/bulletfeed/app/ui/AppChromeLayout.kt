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

/** Which ready-state pane wins. Overlays outrank a still-selected event/alert. */
enum class AppReadyPane {
    EVENT_LIST_DETAIL,
    VULNERABILITY_LIST_DETAIL,
    NOTIFICATIONS,
    GITHUB,
    EVENT_STACKED,
    VULNERABILITY_STACKED,
    MAIN,
    ;

    companion object {
        fun resolve(
            widthDp: Int,
            tab: AppTab,
            selectedEventId: String?,
            selectedVulnerabilityId: String?,
            notificationsOpen: Boolean,
            githubSetupOpen: Boolean,
        ): AppReadyPane {
            val overlayOpen = notificationsOpen || githubSetupOpen
            return when {
                AppChromeLayout.showsEventListDetail(widthDp, tab, selectedEventId, overlayOpen) ->
                    EVENT_LIST_DETAIL
                AppChromeLayout.showsVulnerabilityListDetail(
                    widthDp,
                    tab,
                    selectedEventId,
                    selectedVulnerabilityId,
                    overlayOpen,
                ) -> VULNERABILITY_LIST_DETAIL
                notificationsOpen -> NOTIFICATIONS
                githubSetupOpen -> GITHUB
                selectedEventId != null -> EVENT_STACKED
                selectedVulnerabilityId != null -> VULNERABILITY_STACKED
                else -> MAIN
            }
        }
    }
}

private val EVENT_LIST_DETAIL_TABS = setOf(AppTab.FEED, AppTab.SEARCH)
