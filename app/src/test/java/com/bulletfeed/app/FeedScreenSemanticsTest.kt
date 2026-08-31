package com.bulletfeed.app

import androidx.compose.runtime.Composable
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class FeedScreenSemanticsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun emptyFeedAnnouncesPoliteLiveRegion() {
        composeRule.setContent { FeedHarness() }

        composeRule.onNodeWithText("表示する変化はありません").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
        composeRule.onNodeWithText("BulletFeed").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun loadMoreFailureAnnouncesAssertiveLiveRegion() {
        composeRule.setContent { FeedHarness(loadMoreError = "次のページを読み込めませんでした") }

        composeRule.onNodeWithText("次のページを読み込めませんでした").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
    }
}

@Composable
private fun FeedHarness(loadMoreError: String? = null) {
    FeedScreen(
        events = emptyList(),
        filter = FeedFilter.ALL,
        onFilterChange = {},
        onEventClick = {},
        onFeedback = { _, _ -> },
        onFollow = {},
        securityActionCount = 0,
        onSecurityClick = {},
        unreadNotificationCount = 0,
        onNotificationsClick = {},
        nextCursor = null,
        isLoadingMore = false,
        isFiltering = false,
        loadMoreError = loadMoreError,
        onLoadMore = {},
        onVisibleFeedItems = {},
        onTopicsClick = {},
        onGithubClick = {},
    )
}
