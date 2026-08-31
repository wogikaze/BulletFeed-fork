package com.bulletfeed.app

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
class AppBarTitleSemanticsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun appBarTitleExposesHeadingSemantics() {
        composeRule.setContent { AppBarTitle("BulletFeed") }

        composeRule.onNodeWithText("BulletFeed").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }
}
