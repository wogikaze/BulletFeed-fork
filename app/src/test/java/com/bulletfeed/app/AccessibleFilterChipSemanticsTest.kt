package com.bulletfeed.app

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
}
