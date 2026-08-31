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
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class SiteFeedDiscoverSettingsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun discoverFieldAndButtonMeetTouchTargetAndDoNotSubscribeAutomatically() {
        var discoveredUrl: String? = null
        var subscribed = 0
        composeRule.setContent {
            MaterialTheme {
                SettingsScreen(
                    profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                    isSaving = false,
                    onSaveProfile = {},
                    onAddSubscription = { _, _, _ -> subscribed += 1 },
                    onDiscoverSiteFeeds = { discoveredUrl = it },
                )
            }
        }

        composeRule.onNodeWithTag("site-feed-discover-url", useUnmergedTree = true).assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("site-feed-discover-button").assertHeightIsAtLeast(48.dp)
        composeRule
            .onNodeWithTag("site-feed-discover-url", useUnmergedTree = true)
            .performScrollTo()
            .performTextInput("https://notes.example.com/")
        composeRule.waitForIdle()
        composeRule.onNodeWithText("フィードを探す").performScrollTo().performClick()
        composeRule.waitForIdle()

        assertEquals("https://notes.example.com/", discoveredUrl)
        assertEquals(0, subscribed)
        assertEquals(0, composeRule.onAllNodesWithTag("site-feed-discover-item").fetchSemanticsNodes().size)
    }

    @Test
    fun preferredFeedShowsDiscoveryOnlyAndSubscribeKeeps48dp() {
        var subscribedKind: UserSourceKind? = null
        var subscribedUrl: String? = null
        composeRule.setContent {
            MaterialTheme {
                SettingsScreen(
                    profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                    isSaving = false,
                    onSaveProfile = {},
                    siteFeedDiscoverResult = sampleDiscoverResult(),
                    onAddSubscription = { kind, url, _ ->
                        subscribedKind = kind
                        subscribedUrl = url
                    },
                )
            }
        }

        assertEquals(1, composeRule.onAllNodesWithTag("site-feed-discover-preferred").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("発見のみ。購読するまで証拠には使いません。").fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("証拠には未使用").fetchSemanticsNodes().size)
        composeRule.onNodeWithTag("site-feed-discover-subscribe").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithText("このフィードを購読").performScrollTo().performClick()
        composeRule.waitForIdle()

        assertEquals(UserSourceKind.RSS_ATOM, subscribedKind)
        assertEquals("https://notes.example.com/feed.xml", subscribedUrl)
    }

    @Test
    fun genericWebFallbackExplainsMissingFeed() {
        composeRule.setContent {
            MaterialTheme {
                SettingsScreen(
                    profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                    isSaving = false,
                    onSaveProfile = {},
                    siteFeedDiscoverResult =
                        SiteFeedDiscoverResult(
                            version = "site-feed-discover-v1",
                            siteUrl = "https://plain.example.com/",
                            canonicalSiteUrl = "https://plain.example.com/",
                            preferredFamily = "generic_web",
                            items =
                                listOf(
                                    SiteFeedDiscoverItem(
                                        id = "web-1",
                                        endpointId = "ep-web-1",
                                        canonicalUrl = "https://plain.example.com/",
                                        family = "generic_web",
                                        discoveryMethod = "site_url_fallback",
                                        discoveryProvenance = "website_feed",
                                        title = "Page watch",
                                        preferred = true,
                                        evidenceEligible = false,
                                        discoveryOnly = true,
                                        actionability = SourceActionability.SUBSCRIBE,
                                        verificationStatus = "unverified",
                                        authorityStatus = "unknown",
                                        explanation = "No feed",
                                        siteUrl = "https://plain.example.com/",
                                    ),
                                ),
                        ),
                )
            }
        }

        assertEquals(
            1,
            composeRule.onAllNodesWithText("RSS / Atom / JSON Feed は見つかりませんでした。ページ監視の候補だけを表示しています。")
                .fetchSemanticsNodes()
                .size,
        )
        composeRule.onNodeWithTag("site-feed-discover-subscribe").assertHeightIsAtLeast(48.dp)
        assertEquals(1, composeRule.onAllNodesWithText("Webとして追加").fetchSemanticsNodes().size)
    }

    @Test
    fun discoverErrorAnnouncesAssertiveAndDoesNotLookOffline() {
        composeRule.setContent {
            MaterialTheme {
                SettingsScreen(
                    profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                    isSaving = false,
                    onSaveProfile = {},
                    siteFeedDiscoverError = "URLを入力してください。",
                )
            }
        }

        composeRule.onNodeWithText("URLを入力してください。").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive),
        )
        assertEquals(0, composeRule.onAllNodesWithText("オフラインです").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithTag("offline-recovery-banner").fetchSemanticsNodes().size)
    }

    @Test
    fun emptyDiscoverResultAnnouncesPoliteEmptyWithoutCandidates() {
        composeRule.setContent {
            MaterialTheme {
                SettingsScreen(
                    profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                    isSaving = false,
                    onSaveProfile = {},
                    siteFeedDiscoverResult =
                        SiteFeedDiscoverResult(
                            version = "site-feed-discover-v1",
                            siteUrl = "https://empty.example.com/",
                            canonicalSiteUrl = "https://empty.example.com/",
                            preferredFamily = "rss_atom",
                            items = emptyList(),
                        ),
                )
            }
        }

        composeRule.onNodeWithText("このサイトから購読できるフィードは見つかりませんでした。下の Web として追加できます。").assert(
            SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite),
        )
        assertEquals(0, composeRule.onAllNodesWithTag("site-feed-discover-item").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithTag("site-feed-discover-preferred").fetchSemanticsNodes().size)
        assertEquals(0, composeRule.onAllNodesWithText("オフラインです").fetchSemanticsNodes().size)
    }

    @Test
    fun largeFontScaleKeepsDiscoverTouchTargets() {
        composeRule.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalDensity provides Density(density = 1f, fontScale = AppReadability.LARGE_FONT_SCALE),
                ) {
                    SettingsScreen(
                        profile = UserProfile(role = "Androidエンジニア", interests = setOf("モバイル"), region = "東京"),
                        isSaving = false,
                        onSaveProfile = {},
                        siteFeedDiscoverResult = sampleDiscoverResult(),
                    )
                }
            }
        }

        composeRule.onNodeWithTag("site-feed-discover-url", useUnmergedTree = true).assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("site-feed-discover-button").assertHeightIsAtLeast(48.dp)
        composeRule.onNodeWithTag("site-feed-discover-subscribe").assertHeightIsAtLeast(48.dp)
    }
}

private fun sampleDiscoverResult(): SiteFeedDiscoverResult =
    SiteFeedDiscoverResult(
        version = "site-feed-discover-v1",
        siteUrl = "https://notes.example.com/",
        canonicalSiteUrl = "https://notes.example.com/",
        preferredFamily = "rss_atom",
        items =
            listOf(
                SiteFeedDiscoverItem(
                    id = "feed-1",
                    endpointId = "ep-feed-1",
                    canonicalUrl = "https://notes.example.com/feed.xml",
                    family = "rss_atom",
                    discoveryMethod = "html_link",
                    discoveryProvenance = "site_html_link",
                    title = "Notes",
                    preferred = true,
                    evidenceEligible = false,
                    discoveryOnly = true,
                    actionability = SourceActionability.SUBSCRIBE,
                    verificationStatus = "unverified",
                    authorityStatus = "unknown",
                    explanation = "link rel alternate",
                    siteUrl = "https://notes.example.com/",
                ),
            ),
    )
