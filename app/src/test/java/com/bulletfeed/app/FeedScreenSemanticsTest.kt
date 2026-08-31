package com.bulletfeed.app

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
        composeRule.setContent {
            EmptyFeed(
                filter = FeedFilter.ALL,
                onFilterChange = {},
                onTopicsClick = {},
                onGithubClick = {},
            )
        }

        composeRule.onNodeWithText("表示する変化はありません").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun loadMoreFailureAnnouncesAssertiveLiveRegion() {
        composeRule.setContent { FeedLoadMoreError("次のページを読み込めませんでした") }

        composeRule.onNodeWithText("次のページを読み込めませんでした").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
    }
}
