package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
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
        composeRule.setContent { EmptyDetailSection("追跡できるソースはありません。") }

        composeRule.onNodeWithText("追跡できるソースはありません。").assert(
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
    fun knowledgeBootstrapActionsMeetMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                KnowledgeBootstrapCard(
                    currentState = CurrentState(
                        phase = "released",
                        summary = "1.2.0 が利用可能",
                        since = "2026-08-30T00:00:00Z",
                        confidence = "high",
                    ),
                    following = false,
                    isSaving = false,
                    onMarkCurrentStateKnown = {},
                )
            }
        }

        composeRule.onNodeWithText("この現在状態はすでに知っている").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("これから追う（過去は既知にしない）").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun knowledgeBootstrapPromptDialogButtonsMeetMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                KnowledgeBootstrapPromptDialog(
                    prompt = KnowledgeBootstrapPrompt(
                        subjectKind = BootstrapSubjectKind.EVENT,
                        subjectId = "event-1",
                        title = "Release 1.2.0",
                        currentStateSummary = "1.2.0 が利用可能",
                    ),
                    isSaving = false,
                    onAlreadyKnew = {},
                    onCatchUp = {},
                    onDismiss = {},
                )
            }
        }

        composeRule.onNodeWithText("この現在状態は知っている").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("これから追う").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("あとで").assertHeightIsAtLeast(48.dp)
    }
}
