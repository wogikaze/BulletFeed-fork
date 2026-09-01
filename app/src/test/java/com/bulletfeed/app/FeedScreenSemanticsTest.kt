package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
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
        composeRule.onNodeWithTag("event-card").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsEmptyFeedActionTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    EmptyFeed(
                        filter = FeedFilter.DIRECT,
                        onFilterChange = {},
                        onTopicsClick = {},
                        onGithubClick = {},
                    )
                }
            }
        }

        composeRule.onNodeWithText("すべての変化を見る").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("テーマを追加する").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("GitHubを連携・設定する").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsLoadMoreTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    FeedLoadMoreButton(
                        isLoadingMore = false,
                        enabled = true,
                        onLoadMore = {},
                    )
                }
            }
        }

        composeRule.onNodeWithTag("feed-load-more").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("次のページを読み込む").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun eventCardShowsApiDisplayReasonTextAndKeepsCodesOffScreen() {
        composeRule.setContent {
            MaterialTheme {
                EventCard(
                    event = feedEventWithReason(
                        DisplayReason(
                            policyVersion = "display-reason-v1",
                            rankingPolicyVersion = "ranking-v1",
                            primaryCode = "relation.direct_topic",
                            text = "フォロー中のRustに関連。まだ見ていない可能性が高い。",
                            codes = listOf("relation.direct_topic", "novelty.possibly_unread"),
                            matchKind = "direct",
                            deltaKind = "new_fact",
                        ),
                    ),
                    onClick = {},
                    onFeedback = { _, _ -> },
                    onFollow = {},
                )
            }
        }

        assertEquals(1, composeRule.onAllNodesWithText("フォロー中のRustに関連。まだ見ていない可能性が高い。").fetchSemanticsNodes().size)
        assertEquals(
            1,
            composeRule.onAllNodesWithContentDescription("表示理由: フォロー中のRustに関連。まだ見ていない可能性が高い。")
                .fetchSemanticsNodes()
                .size,
        )
        assertEquals(0, composeRule.onAllNodesWithText("relation.direct_topic").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("novelty.possibly_unread").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("未読です").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("知っている").fetchSemanticsNodes().size)
        composeRule.onNodeWithContentDescription("Event操作").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun displayReasonLineHidesBlankApiTextAndDoesNotShowCodes() {
        composeRule.setContent {
            MaterialTheme {
                FeedDisplayReasonLine(
                    DisplayReason(
                        policyVersion = "display-reason-v1",
                        rankingPolicyVersion = "ranking-v1",
                        primaryCode = "relation.direct_topic",
                        text = "   ",
                        codes = listOf("relation.direct_topic"),
                        matchKind = "direct",
                        deltaKind = "new_fact",
                    ),
                )
            }
        }

        assertEquals(0, composeRule.onAllNodesWithTag("feed-display-reason").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("relation.direct_topic").fetchSemanticsNodes().size)
    }

    @Test
    fun eventCardOmitsReasonLineWhenDisplayReasonIsMissing() {
        composeRule.setContent {
            MaterialTheme {
                EventCard(
                    event = feedEventWithReason(null),
                    onClick = {},
                    onFeedback = { _, _ -> },
                    onFollow = {},
                )
            }
        }

        assertEquals(0, composeRule.onAllNodesWithTag("feed-display-reason").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("表示理由", substring = true).fetchSemanticsNodes().size)
    }

    private fun feedEventWithReason(reason: DisplayReason?) = FeedEvent(
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
        displayReason = reason,
    )
}
