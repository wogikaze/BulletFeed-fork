package com.bulletfeed.app

import android.content.res.Configuration
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
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
        composeRule.onNodeWithTag("app-chrome-tab-feed").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("app-chrome-tab-security").assertHeightIsAtLeast(48.dp)
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
        composeRule.onNodeWithTag("app-chrome-tab-feed").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("app-chrome-tab-settings").assertHeightIsAtLeast(48.dp)
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

    @Test
    fun compactWindowWidthSelectsBottomBarFromConfiguration() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(LocalConfiguration provides widthConfiguration(360)) {
                    AppChromeShellForWindow(
                        tab = AppTab.FEED,
                        securityActionCount = 0,
                        onTabChange = {},
                        content = { _ -> },
                    )
                }
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("app-chrome-bottom-bar").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithTag("app-chrome-navigation-rail").fetchSemanticsNodes().size)
        composeRule.onNodeWithTag("app-chrome-tab-topics").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun landscapePhoneWidthSelectsRailWithoutListDetail() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(LocalConfiguration provides widthConfiguration(800)) {
                    AppChromeShellForWindow(
                        tab = AppTab.FEED,
                        securityActionCount = 0,
                        onTabChange = {},
                        content = { _ -> },
                    )
                }
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("app-chrome-navigation-rail").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithTag("app-chrome-bottom-bar").fetchSemanticsNodes().size)
        composeRule.onNodeWithTag("app-chrome-tab-search").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun expandedWindowWidthSelectsRailFromConfiguration() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(LocalConfiguration provides widthConfiguration(840)) {
                    AppChromeShellForWindow(
                        tab = AppTab.FEED,
                        securityActionCount = 2,
                        onTabChange = {},
                        content = { _ -> },
                    )
                }
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("app-chrome-navigation-rail").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithTag("app-chrome-bottom-bar").fetchSemanticsNodes().size)
        composeRule.onNodeWithTag("app-chrome-tab-security").assertHeightIsAtLeast(48.dp)
    }
}

private fun widthConfiguration(widthDp: Int): Configuration =
    Configuration().apply { screenWidthDp = widthDp }
