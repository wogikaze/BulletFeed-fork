package com.bulletfeed.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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

    @Test
    fun listDetailKeepsOfflineRecoveryBannerOverlay() {
        composeRule.setContent {
            MaterialTheme {
                Box(Modifier.fillMaxSize()) {
                    AppListDetailSplit(
                        list = { Text("list-pane") },
                        detail = { Text("detail-pane") },
                    )
                    OfflineRecoveryBanner(
                        hasStaleFeed = true,
                        onRetry = {},
                        modifier = Modifier.align(Alignment.TopCenter),
                    )
                }
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("app-list-detail").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithTag("offline-recovery-banner").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("オフラインです").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("list-pane").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("detail-pane").fetchSemanticsNodes().size)
    }

    @Test
    fun listDetailKeepsTransientErrorBannerOverlay() {
        composeRule.setContent {
            MaterialTheme {
                Box(Modifier.fillMaxSize()) {
                    AppListDetailSplit(
                        list = { Text("list-pane") },
                        detail = { Text("detail-pane") },
                    )
                    TransientErrorBanner(
                        message = "一時的なエラーです",
                        onDismiss = {},
                        modifier = Modifier.align(Alignment.TopCenter),
                    )
                }
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("app-list-detail").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithTag("transient-error-banner").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("一時的なエラーです").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("list-pane").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("detail-pane").fetchSemanticsNodes().size)
    }
}
