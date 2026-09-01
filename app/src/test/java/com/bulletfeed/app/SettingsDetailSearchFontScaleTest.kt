package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class SettingsDetailSearchFontScaleTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun largeFontScaleKeepsSettingsProfileAndSubscriptionTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    SettingsScreen(
                        profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                        isSaving = false,
                        onSaveProfile = {},
                    )
                }
            }
        }

        composeRule.onNodeWithText("プロフィールを編集").performScrollTo().assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("プロフィールを編集").performClick()
        composeRule.waitForIdle()
        composeRule.onNodeWithTag("profile-role-field", useUnmergedTree = true).assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("保存").performScrollTo().assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("キャンセル").performScrollTo().assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("情報源を追加").performScrollTo().assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("source-subscribe-add").performScrollTo().assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsEventDetailFeedbackTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    EventActionBar(
                        following = false,
                        hasFeedContext = true,
                        onFeedback = {},
                        onFollow = {},
                        onDismiss = {},
                    )
                }
            }
        }

        composeRule.onNodeWithText("知っていた").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("今知った").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("フォロー").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("重要").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("不要").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsSearchQueryAndResultTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    SearchScreen(
                        events =
                            listOf(
                                FeedEvent(
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
                            ),
                        onEventClick = {},
                    )
                }
            }
        }

        composeRule.onNodeWithTag("search-query-field", useUnmergedTree = true).assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("search-result-card").assertHeightIsAtLeast(48.dp)
    }
}
