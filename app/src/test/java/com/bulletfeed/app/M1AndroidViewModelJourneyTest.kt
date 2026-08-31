package com.bulletfeed.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

@OptIn(ExperimentalCoroutinesApi::class)
class M1AndroidViewModelJourneyTest {
    @Test
    fun viewModelReachesReadyFeedForEveryPersona() =
        runTest {
            Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
            try {
                val personas = loadPersonas()
                assertEquals(30, personas.size)
                for (persona in personas) {
                    val viewModel = BulletFeedViewModel(MockBulletFeedRepository())
                    viewModel.completeOnboarding(
                        profile = profileFor(persona),
                        topics = persona.topics,
                        connectGithub = true,
                    )
                    advanceUntilIdle()
                    val state = viewModel.uiState.value
                    assertEquals(persona.personaId, OnboardingState.READY, state.onboardingState)
                    assertTrue(persona.personaId, state.onboardingCompleted)
                    assertTrue(
                        "${persona.personaId} expected a mock feed after onboarding",
                        state.events.isNotEmpty(),
                    )
                    assertEquals(persona.personaId, persona.topics.distinct(), state.topics)
                }
            } finally {
                Dispatchers.resetMain()
            }
        }
}

@Serializable
private data class M1ViewModelPersonaManifest(
    val personas: List<M1ViewModelPersonaFixture>,
)

@Serializable
private data class M1ViewModelPersonaFixture(
    @SerialName("persona_id") val personaId: String,
    val language: String,
    val topics: List<String> = emptyList(),
)

private fun profileFor(persona: M1ViewModelPersonaFixture): UserProfile =
    if (persona.language == "en") {
        UserProfile("Android engineer", setOf("mobile"), "US")
    } else {
        UserProfile("Androidエンジニア", setOf("モバイル"), "東京")
    }

private fun loadPersonas(): List<M1ViewModelPersonaFixture> {
    val json = Json { ignoreUnknownKeys = true }
    return json.decodeFromString<M1ViewModelPersonaManifest>(personaManifestFile().readText()).personas
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
