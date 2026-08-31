package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class AppChromeComposeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun compactWidthShowsBottomBarNotRail() {
        composeRule.setContent {
            MaterialTheme {
                AppChromeShell(
                    chrome = AppChromeLayout.BOTTOM_BAR,
                    tab = AppTab.FEED,
                    securityActionCount = 0,
                    onTabChange = {},
                    content = { _ -> },
                )
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("app-chrome-bottom-bar").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithTag("app-chrome-navigation-rail").fetchSemanticsNodes().size)
    }

    @Test
    fun largeWidthShowsNavigationRailNotBottomBar() {
        composeRule.setContent {
            MaterialTheme {
                AppChromeShell(
                    chrome = AppChromeLayout.NAVIGATION_RAIL,
                    tab = AppTab.FEED,
                    securityActionCount = 0,
                    onTabChange = {},
                    content = { _ -> },
                )
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("app-chrome-navigation-rail").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithTag("app-chrome-bottom-bar").fetchSemanticsNodes().size)
    }

    @Test
    fun listDetailSplitExposesListAndDetailPanes() {
        composeRule.setContent {
            MaterialTheme {
                AppListDetailSplit(
                    list = { Text("list-pane") },
                    detail = { Text("detail-pane") },
                )
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("app-list-detail").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithTag("app-list-pane").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithTag("app-detail-pane").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("list-pane").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("detail-pane").fetchSemanticsNodes().size)
    }
}
