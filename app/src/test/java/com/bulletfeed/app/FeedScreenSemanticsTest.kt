package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.dp
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

    @Test
    fun emptyFeedActionsMeetMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                EmptyFeed(
                    filter = FeedFilter.DIRECT,
                    onFilterChange = {},
                    onTopicsClick = {},
                    onGithubClick = {},
                )
            }
        }

        composeRule.onNodeWithText("すべての変化を見る").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("テーマを追加する").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("GitHubを連携・設定する").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun eventCardOverflowMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                EventCard(
                    event = FeedEvent(
                        id = "event-1",
                        title = "Release",
                        summary = "Summary",
                        importance = Importance.MEDIUM,
                        importanceReason = "reason",
                        relation = Relation.DIRECT,
                        relationReason = "reason",
                        announcedAt = "2026-08-30T00:00:00Z",
                        sourceCount = 1,
                        before = "",
                        after = "new",
                        explicitImpact = "impact",
                        inferredImpact = null,
                        sources = emptyList(),
                        timeline = emptyList(),
                        feedItemId = "feed-1",
                    ),
                    onClick = {},
                    onFeedback = { _, _ -> },
                    onFollow = {},
                )
            }
        }

        composeRule.onNodeWithContentDescription("Event操作").assertHeightIsAtLeast(48.dp)
    }
}
