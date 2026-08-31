package com.bulletfeed.app

import org.junit.Assert.assertEquals
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
}
