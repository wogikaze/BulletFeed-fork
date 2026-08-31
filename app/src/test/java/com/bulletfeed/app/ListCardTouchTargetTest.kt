package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ListCardTouchTargetTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun searchResultCardMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                SearchResultCard(event = sampleFeedEvent(), onClick = {})
            }
        }

        composeRule.onNodeWithTag("search-result-card").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun vulnerabilityCardMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                VulnerabilityCard(alert = sampleAlert(), onClick = {})
            }
        }

        composeRule.onNodeWithTag("vulnerability-card").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun notificationCardMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                NotificationCard(
                    notification =
                        AppNotification(
                            id = "n1",
                            title = "CVE-2026-0001",
                            summary = "依存関係の更新が必要です。",
                            category = NotificationCategory.SECURITY,
                            priority = NotificationPriority.HIGH,
                            occurredAt = "2026-08-31T00:00:00Z",
                            targetType = NotificationTargetType.EVENT,
                            targetId = "e1",
                        ),
                    onClick = {},
                )
            }
        }

        composeRule.onNodeWithTag("notification-card").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun githubRepositoryCardMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                RepositoryChoiceCard(
                    repository =
                        GithubRepositoryChoice(
                            id = "repo-1",
                            fullName = "owner/repo",
                            htmlUrl = "https://github.com/owner/repo",
                            selected = false,
                        ),
                    onToggle = {},
                )
            }
        }

        composeRule.onNodeWithTag("github-repository-card").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun onboardingGithubChoiceMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                GithubChoiceCard(
                    selected = true,
                    title = "GitHubから自動設定",
                    description = "使っている技術を読み取ります。",
                    onClick = {},
                )
            }
        }

        composeRule.onNodeWithTag("onboarding-github-choice").assertHeightIsAtLeast(48.dp)
    }
}

private fun sampleFeedEvent(): FeedEvent =
    FeedEvent(
        id = "event-1",
        title = "Release",
        summary = "Summary",
        importance = Importance.MEDIUM,
        importanceReason = "reason",
        relation = Relation.DIRECT,
        relationReason = "reason",
        announcedAt = "2026-08-30T00:00:00Z",
        sourceCount = 1,
        before = "",
        after = "new",
        explicitImpact = "impact",
        inferredImpact = null,
        sources = emptyList(),
        timeline = emptyList(),
        feedItemId = "feed-1",
    )

private fun sampleAlert(): VulnerabilityAlert =
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
    )
