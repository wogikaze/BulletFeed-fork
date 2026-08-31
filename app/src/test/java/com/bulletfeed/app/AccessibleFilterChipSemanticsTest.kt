package com.bulletfeed.app

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.dp
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class AccessibleFilterChipSemanticsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun filterChipMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleFilterChip(selected = true, label = "すべて 0", onClick = {})
        }

        composeRule.onNodeWithText("すべて 0").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun assistChipMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleAssistChip(label = "高", onClick = {})
        }

        composeRule.onNodeWithText("高").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun primaryRetryButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessiblePrimaryButton(onClick = {}) { Text("再試行") }
        }

        composeRule.onNodeWithText("再試行").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun outlinedButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleOutlinedButton(onClick = {}) { Text("フォロー") }
        }

        composeRule.onNodeWithText("フォロー").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun textButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleTextButton(onClick = {}) { Text("不要") }
        }

        composeRule.onNodeWithText("不要").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun outlinedTextFieldMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleOutlinedTextField(
                value = "",
                onValueChange = {},
                modifier = Modifier.testTag("accessible-outlined-text-field"),
                label = { Text("フィード URL") },
            )
        }

        composeRule.onNodeWithTag("accessible-outlined-text-field").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun iconButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleIconButton(onClick = {}) {
                Icon(Icons.Default.Close, contentDescription = "閉じる")
            }
        }

        composeRule.onNodeWithContentDescription("閉じる").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun searchQueryFieldMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                SearchScreen(events = emptyList(), onEventClick = {})
            }
        }

        composeRule.onNodeWithTag("search-query-field").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun onboardingCustomTopicRowMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                OnboardingCustomTopicRow(
                    customTopic = "Kotlin",
                    onCustomTopicChange = {},
                    onAddCustom = {},
                )
            }
        }

        composeRule.onNodeWithTag("onboarding-custom-topic-field").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithContentDescription("追加").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun notificationsBackMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                NotificationsScreen(
                    notifications = emptyList(),
                    onBack = {},
                    onNotificationClick = {},
                    onMarkAllRead = {},
                )
            }
        }

        composeRule.onNodeWithContentDescription("戻る").assertHeightIsAtLeast(48.dp)
    }
}
