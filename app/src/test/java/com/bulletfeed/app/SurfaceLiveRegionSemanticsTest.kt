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
import androidx.compose.ui.test.onNodeWithContentDescription
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
class SurfaceLiveRegionSemanticsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun searchEmptyResultsAnnouncesPoliteLiveRegion() {
        composeRule.setContent { SearchEmptyResults() }

        composeRule.onNodeWithText("一致するイベントはありません。別の言葉で検索してください。").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun securityEmptyStateAnnouncesPoliteLiveRegion() {
        composeRule.setContent { SecurityEmptyState(SecurityFilter.ALL) }

        composeRule.onNodeWithText("すべての項目はありません").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun notificationEmptyStateAnnouncesPoliteLiveRegion() {
        composeRule.setContent { NotificationEmptyState(NotificationFilter.ALL) }

        composeRule.onNodeWithText("通知はありません").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun appErrorAnnouncesAssertiveLiveRegion() {
        composeRule.setContent { AppErrorScreen("接続を確認してください", onRetry = {}) }

        composeRule.onNodeWithText("読み込みに失敗しました").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
        composeRule.onNodeWithText("再試行").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun offlineBannerAnnouncesPoliteLiveRegion() {
        composeRule.setContent { OfflineRecoveryBanner(hasStaleFeed = false, onRetry = {}) }

        composeRule.onNodeWithText("オフラインです").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
        composeRule.onNodeWithText("再試行").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun detailLoadingAnnouncesPoliteLiveRegion() {
        composeRule.setContent { DetailLoadingScreen("Alertを読み込み中", onBack = {}) }

        composeRule.onNodeWithText("Alertを読み込み中").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
        composeRule.onNodeWithText("戻る").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun detailErrorAnnouncesAssertiveLiveRegion() {
        composeRule.setContent {
            DetailErrorScreen(message = "Alertを表示できません。", onBack = {}, onRetry = {})
        }

        composeRule.onNodeWithText("詳細を表示できません").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
        composeRule.onNodeWithText("再試行").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("戻る").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun transientErrorBannerAnnouncesAssertiveLiveRegion() {
        composeRule.setContent { TransientErrorBanner("一時的なエラーです", onDismiss = {}) }

        composeRule.onNodeWithText("一時的なエラーです").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
        composeRule.onNodeWithContentDescription("閉じる").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun sourceSubscriptionErrorAnnouncesAssertiveLiveRegion() {
        composeRule.setContent { SourceSubscriptionErrorStatus("許可リスト外の URL です") }

        composeRule.onNodeWithText("許可リスト外の URL です").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
    }

    @Test
    fun sourcePartialFailureAnnouncesPoliteLiveRegion() {
        composeRule.setContent { SourcePartialFailureStatus(failingCount = 1) }

        composeRule.onNodeWithText("1件の情報源が失敗中です。他の購読とフィードはそのまま使えます。").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
    }

    @Test
    fun largeFontScaleKeepsOfflineRetryTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    OfflineRecoveryBanner(hasStaleFeed = true, onRetry = {})
                }
            }
        }

        composeRule.onNodeWithText("再試行").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsAppErrorRetryTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    AppErrorScreen("接続を確認してください", onRetry = {})
                }
            }
        }

        composeRule.onNodeWithText("再試行").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsTransientErrorDismissTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    TransientErrorBanner("一時的なエラーです", onDismiss = {})
                }
            }
        }

        composeRule.onNodeWithContentDescription("閉じる").assertHeightIsAtLeast(48.dp)
    }
}
