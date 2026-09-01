package com.bulletfeed.app

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
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
class KnowledgeBootstrapFontScaleTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun largeFontScaleKeepsEventKnowledgeBootstrapActions() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    Column(Modifier.verticalScroll(rememberScrollState())) {
                        KnowledgeBootstrapCard(
                            currentState =
                                CurrentState(
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
            }
        }

        composeRule.onNodeWithTag("knowledge-bootstrap-already-knew").performScrollTo().assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("knowledge-bootstrap-catch-up").performScrollTo().assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsKnowledgeBootstrapPromptDialogButtons() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    KnowledgeBootstrapPromptDialog(
                        prompt =
                            KnowledgeBootstrapPrompt(
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
        }

        composeRule.onNodeWithText("この現在状態は知っている").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("これから追う").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("あとで").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsSettingsBootstrapResetTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    SettingsScreen(
                        profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                        isSaving = false,
                        onSaveProfile = {},
                        knowledgeBootstrap =
                            KnowledgeBootstrapSummary(
                                version = "kb-v1",
                                explicitKnownFactCount = 2,
                                inferredFactCount = 1,
                                checkpoints =
                                    listOf(
                                        KnowledgeBootstrapCheckpoint(
                                            subjectKind = BootstrapSubjectKind.EVENT,
                                            subjectId = "event-1",
                                            asOf = 1_725_000_000L,
                                            catchUp = false,
                                            knownFactCount = 2,
                                        ),
                                    ),
                            ),
                    )
                }
            }
        }

        composeRule.onNodeWithText("bootstrap だけをリセット").performScrollTo().assertHeightIsAtLeast(48.dp)
    }
}
