package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.test.assertDoesNotExist
import androidx.compose.ui.test.assertExists
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
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

        composeRule.onNodeWithTag("app-chrome-bottom-bar").assertExists()
        composeRule.onNodeWithTag("app-chrome-navigation-rail").assertDoesNotExist()
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

        composeRule.onNodeWithTag("app-chrome-navigation-rail").assertExists()
        composeRule.onNodeWithTag("app-chrome-bottom-bar").assertDoesNotExist()
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

        composeRule.onNodeWithTag("app-list-detail").assertExists()
        composeRule.onNodeWithTag("app-list-pane").assertExists()
        composeRule.onNodeWithTag("app-detail-pane").assertExists()
        composeRule.onNodeWithText("list-pane").assertExists()
        composeRule.onNodeWithText("detail-pane").assertExists()
    }
}
