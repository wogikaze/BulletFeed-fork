package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
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
class SourceSubscriptionPartialFailureTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun failingSubscriptionKeepsHealthySubscriptionAndAnnouncesPartialFailure() {
        composeRule.setContent {
            MaterialTheme {
                SettingsScreen(
                    profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                    isSaving = false,
                    onSaveProfile = {},
                    subscriptions =
                        listOf(
                            sampleSubscription(
                                id = "ok-1",
                                displayName = "React",
                                url = "https://react.dev/blog/rss.xml",
                                state = SourceSubscriptionState.OK,
                            ),
                            sampleSubscription(
                                id = "fail-1",
                                displayName = "Broken Feed",
                                url = "https://example.invalid/feed.xml",
                                state = SourceSubscriptionState.FAILING,
                                failureCount = 3,
                            ),
                        ),
                )
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("source-subscription-ok").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithTag("source-subscription-failing").fetchSemanticsNodes().size)
        composeRule.onNodeWithTag("source-subscription-partial-failure").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
        assertEquals(1, composeRule.onAllNodesWithText("連続失敗 3回").fetchSemanticsNodes().size)
        composeRule.onAllNodesWithText("購読を削除")[0].assertHeightIsAtLeast(48.dp)
        composeRule.onAllNodesWithText("購読を削除")[1].assertHeightIsAtLeast(48.dp)
    }
}

private fun sampleSubscription(
    id: String,
    displayName: String,
    url: String,
    state: SourceSubscriptionState,
    failureCount: Int = 0,
): SourceSubscription =
    SourceSubscription(
        id = id,
        kind = "rss_atom",
        canonicalUrl = url,
        publisher = SourcePublisher(slug = id, displayName = displayName),
        selected = true,
        state = state,
        failureCount = failureCount,
    )
