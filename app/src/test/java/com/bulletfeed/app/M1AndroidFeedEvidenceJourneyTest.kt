package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class M1AndroidFeedEvidenceJourneyTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun mockFeedEvidenceIsTraceableForTopicPersonasAndEmptyForAbstention() =
        runTest {
            val personas = loadPersonas()
            assertEquals(30, personas.size)
            val abstaining = personas.filter { it.expectEmptyReason == "no_topics_abstention" }
            assertEquals(listOf("m1p_29", "m1p_30"), abstaining.map { it.personaId })
            for (persona in abstaining) {
                val repository = MockBulletFeedRepository()
                repository.completeOnboarding(
                    profile = profileFor(persona),
                    topics = persona.topics,
                    connectGithub = true,
                )
                assertTrue(
                    "${persona.personaId} intended abstention must not invent feed cards",
                    repository.getFeedEvents().isEmpty(),
                )
            }
            for (persona in personas.filter { it.expectEmptyReason.isEmpty() }) {
                val repository = MockBulletFeedRepository()
                repository.completeOnboarding(
                    profile = profileFor(persona),
                    topics = persona.topics,
                    connectGithub = true,
                )
                val events = repository.getFeedEvents()
                assertTrue("${persona.personaId} expected mock feed items", events.isNotEmpty())
                val event = events.first()
                val detail = repository.getEventDetail(event.id, event.feedItemId)
                assertTrue("${persona.personaId} expected evidence sources", detail.sources.isNotEmpty())
                assertTrue(
                    "${persona.personaId} evidence must be source-grounded text",
                    detail.sources.all { it.evidence.isNotBlank() },
                )
                assertTrue(
                    "${persona.personaId} must not surface claim ids as evidence",
                    detail.sources.none { source ->
                        source.evidence.contains("claim_id", ignoreCase = true) ||
                            source.kind.name.contains("claim_id", ignoreCase = true)
                    },
                )
                repository.updateEventFeedback(event.id, Feedback.ALREADY_KNEW)
            }
        }

    @Test
    fun abstentionPersonasShowEmptyFeedCopy() {
        val persona = loadPersonas().first { it.expectEmptyReason == "no_topics_abstention" }
        val events =
            runBlocking {
                val repository = MockBulletFeedRepository()
                repository.completeOnboarding(
                    profile = profileFor(persona),
                    topics = persona.topics,
                    connectGithub = true,
                )
                repository.getFeedEvents()
            }
        assertTrue(events.isEmpty())
        composeRule.setContent {
            MaterialTheme {
                EmptyFeed(
                    filter = FeedFilter.ALL,
                    onFilterChange = {},
                    onTopicsClick = {},
                    onGithubClick = {},
                )
            }
        }
        composeRule.onNodeWithText("表示する変化はありません").assertExists()
    }

    @Test
    fun feedCardOpensEvidenceAndSendsAlreadyKnewForTopicPersonas() {
        val personas = loadPersonas().filter { it.expectEmptyReason.isEmpty() }
        assertEquals(28, personas.size)
        var current by mutableStateOf(runBlocking { repositoryJourney(personas.first()) })
        var pane by mutableStateOf("card")
        var received: Feedback? = null
        composeRule.setContent {
            MaterialTheme {
                key("${current.personaId}-$pane") {
                    when (pane) {
                        "card" ->
                            EventCard(
                                event = current.event,
                                onClick = { pane = "detail" },
                                onFeedback = { _, _ -> },
                                onFollow = {},
                            )
                        else ->
                            EventDetailScreen(
                                event = current.detail,
                                feedContext = current.event,
                                onBack = { pane = "card" },
                                onFeedback = { received = it },
                                onFollow = {},
                            )
                    }
                }
            }
        }

        for (persona in personas) {
            received = null
            val journey = runBlocking { repositoryJourney(persona) }
            composeRule.runOnIdle {
                current = journey
                pane = "card"
            }
            composeRule.waitForIdle()
            composeRule.onNodeWithTag("event-card").performClick()
            composeRule.waitForIdle()
            composeRule.onNodeWithTag("event-detail-evidence-heading").assertExists()
            composeRule.onNodeWithText("知っていた").performClick()
            composeRule.waitForIdle()
            assertEquals(persona.personaId, Feedback.ALREADY_KNEW, received)
        }
    }
}

private data class M1FeedJourney(
    val personaId: String,
    val event: FeedEvent,
    val detail: EventDetail,
)

@Serializable
private data class M1FeedPersonaManifest(
    val personas: List<M1FeedPersonaFixture>,
)

@Serializable
private data class M1FeedPersonaFixture(
    @SerialName("persona_id") val personaId: String,
    val language: String,
    val topics: List<String> = emptyList(),
    @SerialName("expect_empty_reason") val expectEmptyReason: String = "",
)

private fun profileFor(persona: M1FeedPersonaFixture): UserProfile =
    if (persona.language == "en") {
        UserProfile("Android engineer", setOf("mobile"), "US")
    } else {
        UserProfile("Androidエンジニア", setOf("モバイル"), "東京")
    }

private suspend fun repositoryJourney(persona: M1FeedPersonaFixture): M1FeedJourney {
    val repository = MockBulletFeedRepository()
    repository.completeOnboarding(
        profile = profileFor(persona),
        topics = persona.topics,
        connectGithub = true,
    )
    val event = repository.getFeedEvents().first()
    return M1FeedJourney(
        personaId = persona.personaId,
        event = event,
        detail = repository.getEventDetail(event.id, event.feedItemId),
    )
}

private fun loadPersonas(): List<M1FeedPersonaFixture> {
    val json = Json { ignoreUnknownKeys = true }
    return json.decodeFromString<M1FeedPersonaManifest>(personaManifestFile().readText()).personas
}

private fun personaManifestFile(): File {
    val candidates =
        listOf(
            File("backend/tests/gold/m1_personas/v01/personas.json"),
            File("../backend/tests/gold/m1_personas/v01/personas.json"),
            File("../../backend/tests/gold/m1_personas/v01/personas.json"),
        )
    return candidates.firstOrNull { it.isFile }
        ?: error("M1 persona manifest not found from ${File(".").canonicalPath}")
}
