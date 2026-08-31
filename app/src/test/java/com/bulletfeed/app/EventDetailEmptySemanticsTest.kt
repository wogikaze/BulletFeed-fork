package com.bulletfeed.app

import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
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
}
