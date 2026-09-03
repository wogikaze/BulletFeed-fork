package com.bulletfeed.app

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class OnboardingTopicsFontScaleTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun largeFontScaleKeepsRecommendationAndCustomTopicTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    Column {
                        OnboardingTopicRecommendationActions(onAdd = {}, onIgnore = {})
                        OnboardingCustomTopicRow(
                            customTopic = "Kotlin",
                            onCustomTopicChange = {},
                            onAddCustom = {},
                        )
                    }
                }
            }
        }

        composeRule.onNodeWithTag("onboarding-recommendation-add").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("onboarding-recommendation-ignore").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("表示しない").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("onboarding-custom-topic-field", useUnmergedTree = true).assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("onboarding-custom-topic-add").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithContentDescription("追加").assertHeightIsAtLeast(48.dp)
    }
}
