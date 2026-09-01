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

    @Test
    fun searchScreenPageHeadingExposesHeadingSemantics() {
        composeRule.setContent {
            MaterialTheme {
                SearchScreen(events = emptyList(), onEventClick = {})
            }
        }

        composeRule.onNodeWithTag("section-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun settingsProfileHeadingExposesHeadingSemantics() {
        composeRule.setContent {
            MaterialTheme {
                SettingsScreen(
                    profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                    isSaving = false,
                    onSaveProfile = {},
                )
            }
        }

        composeRule.onNodeWithTag("section-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
        composeRule.onNodeWithTag("settings-knowledge-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
        composeRule.onNodeWithTag("settings-site-feed-discover-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
        composeRule.onNodeWithTag("settings-subscriptions-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
        composeRule.onNodeWithTag("settings-recommendations-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun githubConnectionHeadingExposesHeadingSemantics() {
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

        composeRule.onNodeWithTag("github-connection-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun todayPriorityEventMeetsMinimumTouchTargetHeight() {
        composeRule.setContent {
            MaterialTheme {
                TodaySummary(
                    urgentEvents =
                        listOf(
                            FeedEvent(
                                id = "event-1",
                                title = "Breaking release",
                                summary = "Summary",
                                importance = Importance.HIGH,
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
                            ),
                        ),
                    directUnreadCount = 1,
                    onEventClick = {},
                )
            }
        }

        composeRule.onNodeWithTag("today-priority-event").assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun eventDetailSectionHeadingsExposeHeadingSemantics() {
        composeRule.setContent {
            MaterialTheme {
                EventDetailScreen(
                    event = sampleEventDetail(),
                    feedContext = null,
                    onBack = {},
                    onFeedback = {},
                    onFollow = {},
                )
            }
        }

        composeRule.onNodeWithTag("event-detail-delta-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
        composeRule.onNodeWithTag("event-detail-unknown-facts-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
        composeRule.onNodeWithTag("event-detail-timeline-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
        composeRule.onNodeWithTag("event-detail-evidence-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun vulnerabilityUpdateHeadingExposesHeadingSemantics() {
        composeRule.setContent {
            MaterialTheme {
                VulnerabilityDetailScreen(
                    alert = sampleVulnerabilityAlert(),
                    onBack = {},
                    onStatusChange = {},
                )
            }
        }

        composeRule.onNodeWithTag("vulnerability-update-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }

    @Test
    fun onboardingStepHeadingExposesHeadingSemantics() {
        composeRule.setContent {
            MaterialTheme {
                OnboardingScreen(
                    initialProfile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                    initialTopics = emptyList(),
                    isSaving = false,
                    onComplete = { _, _, _ -> },
                )
            }
        }

        composeRule.onNodeWithTag("onboarding-step-heading").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.Heading, Unit),
        )
    }
}

private fun sampleEventDetail(): EventDetail =
    EventDetail(
        id = "event-1",
        title = "Release",
        summary = "Summary",
        currentState =
            CurrentState(
                phase = "identified",
                summary = "Shipping",
                since = "2026-08-31T00:00:00Z",
                confidence = "high",
            ),
        latestDelta =
            FeedDelta(
                id = "delta-1",
                type = DeltaType.NEW_FACT,
                summary = "shipped",
                before = "",
                after = "1.0",
                occurredAt = "2026-08-31T00:00:00Z",
            ),
        openedDelta = null,
        timeline = emptyList(),
        impacts = emptyList(),
        sources = emptyList(),
        following = false,
    )

private fun sampleVulnerabilityAlert(): VulnerabilityAlert =
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
