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
class SessionRecoverySemanticsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun reauthenticationAnnouncesAssertiveLiveRegion() {
        composeRule.setContent { ReauthenticationScreen(isAuthorizing = false, onReauthenticate = {}) }

        composeRule.onNodeWithText("同じアカウントへ再認証").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
        composeRule.onNodeWithText("同じアカウントへ再認証").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun githubReauthorizationAnnouncesAssertiveLiveRegion() {
        composeRule.setContent {
            GithubReauthorizationRequiredScreen(
                accountLogin = "octocat",
                isAuthorizing = false,
                showBack = false,
                onBack = {},
                onAuthorize = {},
            )
        }

        composeRule.onNodeWithText("GitHubの再認証が必要です").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
    }

    @Test
    fun loadingScreenAnnouncesPoliteLiveRegion() {
        composeRule.setContent { AppLoadingScreen() }

        composeRule.onNodeWithText("データを読み込み中…").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }
}
