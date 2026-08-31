package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class EventDetailFeedbackActionsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun alreadyKnewSendsAlreadyKnewFeedback() {
        val received = mutableListOf<Feedback>()
        composeRule.setContent {
            MaterialTheme {
                EventActionBar(
                    following = false,
                    hasFeedContext = true,
                    onFeedback = { received += it },
                    onFollow = {},
                    onDismiss = {},
                )
            }
        }

        composeRule.onNodeWithText("知っていた").performClick()
        assertEquals(listOf(Feedback.ALREADY_KNEW), received)
    }

    @Test
    fun learnedNowSendsLearnedNowFeedback() {
        val received = mutableListOf<Feedback>()
        composeRule.setContent {
            MaterialTheme {
                EventActionBar(
                    following = false,
                    hasFeedContext = true,
                    onFeedback = { received += it },
                    onFollow = {},
                    onDismiss = {},
                )
            }
        }

        composeRule.onNodeWithText("今知った").performClick()
        assertEquals(listOf(Feedback.LEARNED_NOW), received)
    }

    @Test
    fun knowledgeFeedbackButtonsMeetMinimumTouchTargetHeight() {
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

        composeRule.onNodeWithText("知っていた").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("今知った").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun knowledgeFeedbackButtonsHiddenWithoutFeedContext() {
        composeRule.setContent {
            MaterialTheme {
                EventActionBar(
                    following = false,
                    hasFeedContext = false,
                    onFeedback = {},
                    onFollow = {},
                    onDismiss = {},
                )
            }
        }

        assertEquals(0, composeRule.onAllNodesWithText("知っていた").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("今知った").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("重要").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("不要").fetchSemanticsNodes().size)
    }

    @Test
    fun knowledgeFeedbackDoesNotSendRankingSignals() {
        val received = mutableListOf<Feedback>()
        composeRule.setContent {
            MaterialTheme {
                EventActionBar(
                    following = true,
                    hasFeedContext = true,
                    onFeedback = { received += it },
                    onFollow = {},
                    onDismiss = {},
                )
            }
        }

        composeRule.onNodeWithText("知っていた").performClick()
        composeRule.onNodeWithText("今知った").performClick()
        assertEquals(listOf(Feedback.ALREADY_KNEW, Feedback.LEARNED_NOW), received)
        assertTrue(received.none { it == Feedback.IMPORTANT || it == Feedback.NOT_RELEVANT })
    }
}
