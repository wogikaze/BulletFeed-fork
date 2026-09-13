package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class EventDetailEmptySemanticsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun emptyTimelineAnnouncesPoliteLiveRegion() {
        composeRule.setContent { EmptyDetailSection("時系列情報はありません。") }

        composeRule.onNodeWithText("時系列情報はありません。").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun emptySourcesAnnouncesPoliteLiveRegion() {
        composeRule.setContent { EmptyDetailSection("参照できる情報源はありません。") }

        composeRule.onNodeWithText("参照できる情報源はありません。").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun eventActionBarButtonsMeetMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                EventActionBar(
                    following = false,
                    hasFeedContext = true,
                    onFeedback = {},
                    onFollow = {},
                    onDismiss = {},
                )
            }
        }

        composeRule.onNodeWithText("不要").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("フォロー").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("重要").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("知っていた").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("今知った").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsSourceOpenTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    EventSourceCard(
                        source = EventSource(
                            publisher = "Statuspage",
                            kind = SourceKind.STATUSPAGE,
                            title = "API latency",
                            url = "https://stspg.io/inc_android_acceptance",
                            publishedAt = "2026-08-22T00:00:00Z",
                            retrievedAt = "2026-08-22T00:11:00Z",
                            evidence = "Investigating elevated latency.",
                        ),
                    )
                }
            }
        }

        composeRule.onNodeWithText("情報源を開く").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun emptyUnknownFactsAnnouncesPoliteLiveRegion() {
        composeRule.setContent { UnknownFactsCard(emptyList()) }

        composeRule.onNodeWithText("この更新について、未確認の事実はありません。").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun unknownFactsListShowsBulletText() {
        composeRule.setContent {
            MaterialTheme {
                UnknownFactsCard(listOf(UnknownFact("f1", "原因はランタイムの飽和です。")))
            }
        }

        composeRule.onNodeWithText("未確認の事実（1）").assertExists()
        composeRule.onNodeWithText("原因はランタイムの飽和です。").assertExists()
    }

    @Test
    fun eventDetailShowsUnknownFactsAndHidesDeltaUntilExpanded() {
        composeRule.setContent {
            MaterialTheme {
                EventDetailScreen(
                    event = EventDetail(
                        id = "event-1",
                        title = "Release",
                        summary = "Summary",
                        currentState = CurrentState(
                            phase = "identified",
                            summary = "Shipping",
                            since = "2026-08-31T00:00:00Z",
                            confidence = "high",
                        ),
                        latestDelta = FeedDelta(
                            id = "delta-1",
                            type = DeltaType.NEW_FACT,
                            summary = "shipped",
                            before = "なし",
                            after = "1.0",
                            occurredAt = "2026-08-31T00:00:00Z",
                        ),
                        openedDelta = null,
                        unknownFacts = listOf(UnknownFact("f1", "1.0 が公開された。")),
                        timeline = emptyList(),
                        impacts = emptyList(),
                        sources = emptyList(),
                        following = false,
                    ),
                    feedContext = null,
                    onBack = {},
                    onFeedback = {},
                    onFollow = {},
                )
            }
        }

        composeRule.onNodeWithText("1.0 が公開された。").assertExists()
        composeRule.onAllNodesWithText("変更前").assertCountEquals(0)
        composeRule.onNodeWithText("変更前後を表示").assertExists()
    }

    @Test
    fun deltaAccordionStartsCollapsedAndExpands() {
        composeRule.setContent {
            MaterialTheme {
                DeltaAccordion(
                    FeedDelta(
                        id = "delta-1",
                        type = DeltaType.NEW_FACT,
                        summary = "shipped",
                        before = "なし",
                        after = "1.0",
                        occurredAt = "2026-08-31T00:00:00Z",
                    ),
                )
            }
        }

        composeRule.onAllNodesWithText("変更前").assertCountEquals(0)
        composeRule.onNodeWithTag("event-detail-delta-toggle").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("event-detail-delta-toggle").performClick()
        composeRule.onNodeWithText("変更前").assertExists()
        composeRule.onNodeWithText("なし").assertExists()
    }
}
