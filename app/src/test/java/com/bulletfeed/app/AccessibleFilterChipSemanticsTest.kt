package com.bulletfeed.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
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

    @Test
    fun assistChipMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleAssistChip(label = "高", onClick = {})
        }

        composeRule.onNodeWithText("高").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun primaryRetryButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessiblePrimaryButton(onClick = {}) { Text("再試行") }
        }

        composeRule.onNodeWithText("再試行").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun outlinedButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleOutlinedButton(onClick = {}) { Text("フォロー") }
        }

        composeRule.onNodeWithText("フォロー").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun textButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleTextButton(onClick = {}) { Text("不要") }
        }

        composeRule.onNodeWithText("不要").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun outlinedTextFieldMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleOutlinedTextField(
                value = "",
                onValueChange = {},
                modifier = Modifier.testTag("accessible-outlined-text-field"),
                label = { Text("フィード URL") },
            )
        }

        composeRule.onNodeWithTag("accessible-outlined-text-field").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun iconButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            AccessibleIconButton(onClick = {}) {
                Icon(Icons.Default.Close, contentDescription = "閉じる")
            }
        }

        composeRule.onNodeWithContentDescription("閉じる").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun searchQueryFieldMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                SearchScreen(events = emptyList(), onEventClick = {})
            }
        }

        composeRule.onNodeWithTag("search-query-field").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun onboardingCustomTopicRowMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                OnboardingCustomTopicRow(
                    customTopic = "Kotlin",
                    onCustomTopicChange = {},
                    onAddCustom = {},
                )
            }
        }

        composeRule.onNodeWithTag("onboarding-custom-topic-field").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithContentDescription("追加").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun notificationsBackMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                NotificationsScreen(
                    notifications = emptyList(),
                    onBack = {},
                    onNotificationClick = {},
                    onMarkAllRead = {},
                )
            }
        }

        composeRule.onNodeWithContentDescription("戻る").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsNotificationsBackTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    NotificationsScreen(
                        notifications = emptyList(),
                        onBack = {},
                        onNotificationClick = {},
                        onMarkAllRead = {},
                    )
                }
            }
        }

        composeRule.onNodeWithContentDescription("戻る").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun notificationsMarkAllReadMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                NotificationsScreen(
                    notifications =
                        listOf(
                            AppNotification(
                                id = "n1",
                                title = "CVE-2026-0001",
                                summary = "依存関係の更新が必要です。",
                                category = NotificationCategory.SECURITY,
                                priority = NotificationPriority.HIGH,
                                occurredAt = "2026-08-31T00:00:00Z",
                                targetType = NotificationTargetType.EVENT,
                                targetId = "e1",
                                read = false,
                            ),
                        ),
                    onBack = {},
                    onNotificationClick = {},
                    onMarkAllRead = {},
                )
            }
        }

        composeRule.onNodeWithText("すべて既読").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun vulnerabilityActionBarMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                VulnerabilityDetailScreen(
                    alert =
                        VulnerabilityAlert(
                            id = "v1",
                            advisoryId = "GHSA-xxxx",
                            cve = "CVE-2026-0001",
                            title = "依存関係の脆弱性",
                            summary = "更新してください。",
                            severity = VulnerabilitySeverity.HIGH,
                            status = VulnerabilityStatus.OPEN,
                            repository = "owner/repo",
                            packageName = "example",
                            currentVersion = "1.0.0",
                            fixedVersion = "1.0.1",
                            dependencyType = DependencyType.DIRECT,
                            detectedAt = "2026-08-31T00:00:00Z",
                            source = "github",
                            evidence = "advisory",
                            recommendation = "1.0.1 に更新",
                            cvssScore = 8.1,
                        ),
                    onBack = {},
                    onStatusChange = {},
                )
            }
        }

        composeRule.onNodeWithText("対象外").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("対応を開始").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun githubAuthorizeButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                GithubConnectionScreen(
                    connection = GithubConnection(connected = false),
                    repositories = emptyList(),
                    nextCursor = null,
                    query = "",
                    isLoading = false,
                    isLoadingMore = false,
                    isSaving = false,
                    isAuthorizing = false,
                    errorMessage = null,
                    onBack = {},
                    onConnect = {},
                    onSearch = {},
                    onLoadMore = {},
                    onToggleRepository = {},
                    onSaveRepositories = {},
                    onImportRepo = {},
                    onDisconnect = {},
                )
            }
        }

        composeRule.onNodeWithTag("github-authorize-button").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsGithubAuthorizeTouchTarget() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    GithubConnectionScreen(
                        connection = GithubConnection(connected = false),
                        repositories = emptyList(),
                        nextCursor = null,
                        query = "",
                        isLoading = false,
                        isLoadingMore = false,
                        isSaving = false,
                        isAuthorizing = false,
                        errorMessage = null,
                        onBack = {},
                        onConnect = {},
                        onSearch = {},
                        onLoadMore = {},
                        onToggleRepository = {},
                        onSaveRepositories = {},
                        onImportRepo = {},
                        onDisconnect = {},
                    )
                }
            }
        }

        composeRule.onNodeWithTag("github-authorize-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithContentDescription("戻る").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("github-import-repo-field").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("github-import-repo-button").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsGithubSaveAndDisconnectTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    Box(Modifier.requiredSize(width = 400.dp, height = 2000.dp)) {
                        GithubConnectionScreen(
                            connection = GithubConnection(connected = true, accountLogin = "octocat"),
                            repositories = emptyList(),
                            nextCursor = "cursor-2",
                            query = "",
                            isLoading = false,
                            isLoadingMore = false,
                            isSaving = false,
                            isAuthorizing = false,
                            errorMessage = null,
                            onBack = {},
                            onConnect = {},
                            onSearch = {},
                            onLoadMore = {},
                            onToggleRepository = {},
                            onSaveRepositories = {},
                            onImportRepo = {},
                            onDisconnect = {},
                        )
                    }
                }
            }
        }

        composeRule.onNodeWithContentDescription("戻る").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("github-repo-search-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("github-load-more-button").performScrollTo().assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("github-save-repositories-button").performScrollTo().assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("github-disconnect-button").performScrollTo().assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun onboardingNextButtonMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                OnboardingScreen(
                    initialProfile =
                        UserProfile(
                            role = "Androidエンジニア",
                            interests = setOf("モバイル"),
                            region = "東京",
                        ),
                    initialTopics = emptyList(),
                    isSaving = false,
                    onComplete = { _, _, _ -> },
                )
            }
        }

        composeRule.onNodeWithText("次へ").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("onboarding-continue-button").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun largeFontScaleKeepsOnboardingContinueAndBackTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    OnboardingScreen(
                        initialProfile =
                            UserProfile(
                                role = "Androidエンジニア",
                                interests = setOf("モバイル"),
                                region = "東京",
                            ),
                        initialTopics = emptyList(),
                        isSaving = false,
                        onComplete = { _, _, _ -> },
                    )
                }
            }
        }

        composeRule.onNodeWithTag("onboarding-continue-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("onboarding-continue-button").performClick()
        composeRule.waitForIdle()
        composeRule.onNodeWithText("戻る").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("onboarding-continue-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("onboarding-continue-button").performClick()
        composeRule.waitForIdle()
        composeRule.onNodeWithText("戻る").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("onboarding-continue-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("GitHubから自動設定を始める").assertHeightIsAtLeast(48.dp)
    }
}
