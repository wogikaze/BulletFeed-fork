package com.bulletfeed.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppChromeLayoutTest {
    @Test
    fun compactPhoneUsesBottomBar() {
        assertEquals(AppChromeLayout.BOTTOM_BAR, AppChromeLayout.fromWidthDp(360))
        assertEquals(AppChromeLayout.BOTTOM_BAR, AppChromeLayout.fromWidthDp(599))
    }

    @Test
    fun tabletAndLargeScreenUseNavigationRail() {
        assertEquals(AppChromeLayout.NAVIGATION_RAIL, AppChromeLayout.fromWidthDp(600))
        assertEquals(AppChromeLayout.NAVIGATION_RAIL, AppChromeLayout.fromWidthDp(840))
        assertEquals(AppChromeLayout.NAVIGATION_RAIL, AppChromeLayout.fromWidthDp(1280))
    }

    @Test
    fun listDetailStartsAtExpandedWidth() {
        assertFalse(AppChromeLayout.usesListDetail(600))
        assertFalse(AppChromeLayout.usesListDetail(839))
        assertTrue(AppChromeLayout.usesListDetail(840))
        assertTrue(AppChromeLayout.usesListDetail(1280))
    }

    @Test
    fun landscapePhoneUsesRailWithoutListDetail() {
        assertEquals(AppChromeLayout.NAVIGATION_RAIL, AppChromeLayout.fromWidthDp(800))
        assertFalse(AppChromeLayout.usesListDetail(800))
        assertFalse(
            AppChromeLayout.showsEventListDetail(800, AppTab.FEED, "event-1", overlayOpen = false),
        )
    }

    @Test
    fun eventListDetailRequiresExpandedFeedOrSearch() {
        assertTrue(
            AppChromeLayout.showsEventListDetail(840, AppTab.FEED, "event-1", overlayOpen = false),
        )
        assertTrue(
            AppChromeLayout.showsEventListDetail(840, AppTab.SEARCH, "event-1", overlayOpen = false),
        )
        assertFalse(
            AppChromeLayout.showsEventListDetail(840, AppTab.SETTINGS, "event-1", overlayOpen = false),
        )
        assertFalse(
            AppChromeLayout.showsEventListDetail(839, AppTab.FEED, "event-1", overlayOpen = false),
        )
        assertFalse(
            AppChromeLayout.showsEventListDetail(840, AppTab.FEED, "event-1", overlayOpen = true),
        )
        assertFalse(
            AppChromeLayout.showsEventListDetail(840, AppTab.FEED, null, overlayOpen = false),
        )
    }

    @Test
    fun vulnerabilityListDetailRequiresExpandedSecurityWithoutEvent() {
        assertTrue(
            AppChromeLayout.showsVulnerabilityListDetail(
                840,
                AppTab.SECURITY,
                selectedEventId = null,
                selectedVulnerabilityId = "alert-1",
                overlayOpen = false,
            ),
        )
        assertFalse(
            AppChromeLayout.showsVulnerabilityListDetail(
                840,
                AppTab.SECURITY,
                selectedEventId = "event-1",
                selectedVulnerabilityId = "alert-1",
                overlayOpen = false,
            ),
        )
        assertFalse(
            AppChromeLayout.showsVulnerabilityListDetail(
                840,
                AppTab.FEED,
                selectedEventId = null,
                selectedVulnerabilityId = "alert-1",
                overlayOpen = false,
            ),
        )
        assertFalse(
            AppChromeLayout.showsVulnerabilityListDetail(
                840,
                AppTab.SECURITY,
                selectedEventId = null,
                selectedVulnerabilityId = "alert-1",
                overlayOpen = true,
            ),
        )
    }

    @Test
    fun expandedEventStaysListDetailUntilOverlayOpens() {
        assertEquals(
            AppReadyPane.EVENT_LIST_DETAIL,
            AppReadyPane.resolve(
                widthDp = 840,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
        assertEquals(
            AppReadyPane.NOTIFICATIONS,
            AppReadyPane.resolve(
                widthDp = 840,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = true,
                githubSetupOpen = false,
            ),
        )
        assertEquals(
            AppReadyPane.GITHUB,
            AppReadyPane.resolve(
                widthDp = 840,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = false,
                githubSetupOpen = true,
            ),
        )
    }

    @Test
    fun compactEventGivesWayToNotificationsOverlay() {
        assertEquals(
            AppReadyPane.EVENT_STACKED,
            AppReadyPane.resolve(
                widthDp = 360,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
        assertEquals(
            AppReadyPane.NOTIFICATIONS,
            AppReadyPane.resolve(
                widthDp = 360,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = true,
                githubSetupOpen = false,
            ),
        )
    }

    @Test
    fun widthChangeFromPhoneToExpandedSwitchesStackedEventToListDetail() {
        assertEquals(
            AppReadyPane.EVENT_STACKED,
            AppReadyPane.resolve(
                widthDp = 360,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
        assertEquals(
            AppReadyPane.EVENT_STACKED,
            AppReadyPane.resolve(
                widthDp = 800,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
        assertEquals(
            AppReadyPane.EVENT_LIST_DETAIL,
            AppReadyPane.resolve(
                widthDp = 840,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
        assertEquals(
            AppReadyPane.EVENT_STACKED,
            AppReadyPane.resolve(
                widthDp = 360,
                tab = AppTab.FEED,
                selectedEventId = "event-1",
                selectedVulnerabilityId = null,
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
    }

    @Test
    fun widthChangeFromPhoneToExpandedSwitchesStackedVulnerabilityToListDetail() {
        assertEquals(
            AppReadyPane.VULNERABILITY_STACKED,
            AppReadyPane.resolve(
                widthDp = 360,
                tab = AppTab.SECURITY,
                selectedEventId = null,
                selectedVulnerabilityId = "alert-1",
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
        assertEquals(
            AppReadyPane.VULNERABILITY_LIST_DETAIL,
            AppReadyPane.resolve(
                widthDp = 840,
                tab = AppTab.SECURITY,
                selectedEventId = null,
                selectedVulnerabilityId = "alert-1",
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
    }

    @Test
    fun expandedVulnerabilityGivesWayToNotificationsOverlay() {
        assertEquals(
            AppReadyPane.VULNERABILITY_LIST_DETAIL,
            AppReadyPane.resolve(
                widthDp = 840,
                tab = AppTab.SECURITY,
                selectedEventId = null,
                selectedVulnerabilityId = "alert-1",
                notificationsOpen = false,
                githubSetupOpen = false,
            ),
        )
        assertEquals(
            AppReadyPane.NOTIFICATIONS,
            AppReadyPane.resolve(
                widthDp = 840,
                tab = AppTab.SECURITY,
                selectedEventId = null,
                selectedVulnerabilityId = "alert-1",
                notificationsOpen = true,
                githubSetupOpen = false,
            ),
        )
    }
}
