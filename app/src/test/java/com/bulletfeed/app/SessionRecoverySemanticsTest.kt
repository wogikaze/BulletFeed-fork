package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
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
        composeRule.onNodeWithTag("session-reauth-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("アカウントを復旧").assertHeightIsAtLeast(48.dp)
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
        composeRule.onNodeWithTag("github-reauthorize-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("GitHubを再認証").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun loadingScreenAnnouncesPoliteLiveRegion() {
        composeRule.setContent { AppLoadingScreen() }

        composeRule.onNodeWithText("データを読み込み中…").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun githubAuthorizationErrorAnnouncesAssertiveLiveRegion() {
        composeRule.setContent {
            GithubAuthorizationRequiredScreen(
                isAuthorizing = false,
                errorMessage = "認可に失敗しました",
                onAuthorize = {},
            )
        }

        composeRule.onNodeWithText("GitHub連携を完了").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
        composeRule.onNodeWithText("GitHubで認可する").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("github-oauth-required-authorize").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsReauthenticationButtonTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    ReauthenticationScreen(isAuthorizing = false, onReauthenticate = {})
                }
            }
        }

        composeRule.onNodeWithTag("session-reauth-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("アカウントを復旧").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsGithubReauthorizationButtonTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    GithubReauthorizationRequiredScreen(
                        accountLogin = "octocat",
                        isAuthorizing = false,
                        showBack = true,
                        onBack = {},
                        onAuthorize = {},
                    )
                }
            }
        }

        composeRule.onNodeWithTag("github-reauthorize-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("github-reauthorize-back").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("GitHubを再認証").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("戻る").assertHeightIsAtLeast(48.dp)
    }
}
