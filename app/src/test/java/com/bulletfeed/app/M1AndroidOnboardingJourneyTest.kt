package com.bulletfeed.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
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
import retrofit2.HttpException
import java.io.File

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class M1AndroidOnboardingJourneyTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun manifestContainsThirtyConstructedPersonas() {
        val personas = loadPersonas()

        assertEquals(30, personas.size)
        assertEquals(30, personas.map { it.personaId }.toSet().size)
        assertEquals(
            listOf("m1p_29", "m1p_30"),
            personas.filter { it.expectEmptyReason == "no_topics_abstention" }.map { it.personaId },
        )
        assertTrue(personas.filter { it.expectEmptyReason.isEmpty() }.all { it.topics.isNotEmpty() })
    }

    @Test
    fun mockRepositoryCompletesOnboardingForEveryPersona() =
        runTest {
            for (persona in loadPersonas()) {
                val repository = MockBulletFeedRepository()
                val profile = profileFor(persona)
                val snapshot =
                    repository.completeOnboarding(
                        profile = profile,
                        topics = persona.topics,
                        connectGithub = true,
                    )

                assertTrue(persona.personaId, snapshot.completed)
                assertEquals(persona.personaId, OnboardingState.READY, snapshot.state)
                assertEquals(persona.personaId, profile, snapshot.profile)
                assertEquals(persona.personaId, persona.topics.distinct(), snapshot.topics)
                assertTrue(persona.personaId, repository.getGithubConnection())
            }
        }

    @Test
    fun completeOnboardingWithoutGithubAndTooFewTopicsIsUnprocessable() =
        runTest {
            val persona = loadPersonas().first { it.expectEmptyReason == "no_topics_abstention" }
            val repository = MockBulletFeedRepository()
            try {
                repository.completeOnboarding(
                    profile = profileFor(persona),
                    topics = emptyList(),
                    connectGithub = false,
                )
                throw AssertionError("${persona.personaId} expected HTTP 422 abstention")
            } catch (error: HttpException) {
                assertEquals(422, error.code())
            }
            val snapshot = repository.getOnboardingSnapshot()
            assertEquals(persona.personaId, false, snapshot.completed)
            assertEquals(persona.personaId, OnboardingState.PROFILE, snapshot.state)
        }

    @Test
    fun onboardingScreenCompletesGithubShortcutForEveryPersona() {
        val personas = loadPersonas()
        var current by mutableStateOf(personas.first())
        var completedTopics: List<String>? = null
        var completedGithub: Boolean? = null
        composeRule.setContent {
            MaterialTheme {
                key(current.personaId) {
                    OnboardingScreen(
                        initialProfile = profileFor(current),
                        initialTopics = current.topics,
                        isSaving = false,
                        onComplete = { _, topics, connectGithub ->
                            completedTopics = topics
                            completedGithub = connectGithub
                        },
                    )
                }
            }
        }

        for (persona in personas) {
            completedTopics = null
            completedGithub = null
            composeRule.runOnIdle { current = persona }
            composeRule.waitForIdle()
            composeRule.onNodeWithTag("onboarding-continue-button").performClick()
            composeRule.onNodeWithTag("onboarding-continue-button").performClick()
            composeRule.onNodeWithTag("onboarding-continue-button").performClick()
            composeRule.waitForIdle()
            assertEquals(persona.personaId, persona.topics.distinct(), completedTopics)
            assertEquals(persona.personaId, true, completedGithub)
        }
    }
}

@Serializable
private data class M1PersonaManifest(
    val personas: List<M1PersonaFixture>,
)

@Serializable
private data class M1PersonaFixture(
    @SerialName("persona_id") val personaId: String,
    val language: String,
    val topics: List<String> = emptyList(),
    @SerialName("expect_empty_reason") val expectEmptyReason: String = "",
)

private fun profileFor(persona: M1PersonaFixture): UserProfile =
    if (persona.language == "en") {
        UserProfile("Android engineer", setOf("mobile"), "US")
    } else {
        UserProfile("Androidエンジニア", setOf("モバイル"), "東京")
    }

private fun loadPersonas(): List<M1PersonaFixture> {
    val json =
        Json {
            ignoreUnknownKeys = true
        }
    val body = personaManifestFile().readText()
    return json.decodeFromString<M1PersonaManifest>(body).personas
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
