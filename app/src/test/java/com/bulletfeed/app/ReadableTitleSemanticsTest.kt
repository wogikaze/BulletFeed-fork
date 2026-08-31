package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.unit.Density
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ReadableTitleSemanticsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun defaultFontScaleUsesCompactTitleAndSummaryLineClamp() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(LocalDensity provides Density(density = 1f, fontScale = 1f)) {
                    ReadableTitle("title")
                    ReadableSummary("summary")
                }
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("readable-title-max-lines-2").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithTag("readable-summary-max-lines-3").fetchSemanticsNodes().size)
    }

    @Test
    fun largeFontScaleRaisesTitleAndSummaryLineClamp() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    ReadableTitle("title")
                    ReadableSummary("summary")
                }
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("readable-title-max-lines-4").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithTag("readable-summary-max-lines-6").fetchSemanticsNodes().size)
    }
}
