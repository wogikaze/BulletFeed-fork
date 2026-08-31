package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
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

    @Test
    fun sectionHeadingExposesHeadingSemantics() {
        composeRule.setContent { SectionHeading("すべての変化") }

        composeRule.onNodeWithTag("section-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun securityDashboardSectionHeadingExposesHeadingSemantics() {
        composeRule.setContent {
            MaterialTheme {
                SecurityDashboardScreen(alerts = emptyList(), onAlertClick = {})
            }
        }

        composeRule.onNodeWithTag("section-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun securityShortcutMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                SecurityShortcut(actionCount = 2, onClick = {})
            }
        }

        composeRule.onNodeWithTag("security-shortcut").assertHeightIsAtLeast(48.dp)
    }
}
