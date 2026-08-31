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
class PoliteEmptyStatusSemanticsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun managementEmptyCopyAnnouncesPoliteLiveRegion() {
        composeRule.setContent {
            PoliteEmptyStatus("まだ購読はありません。")
        }

        composeRule.onNodeWithText("まだ購読はありません。").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }
}
