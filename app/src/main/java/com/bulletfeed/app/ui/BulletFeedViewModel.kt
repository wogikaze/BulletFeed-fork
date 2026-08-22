package com.bulletfeed.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class BulletFeedUiState(
    val events: List<FeedEvent> = emptyList(),
    val vulnerabilityAlerts: List<VulnerabilityAlert> = emptyList(),
    val notifications: List<AppNotification> = emptyList(),
    val githubConnected: Boolean = false,
    val onboardingCompleted: Boolean = true,
    val profile: UserProfile = UserProfile("", emptySet(), ""),
    val topics: List<String> = emptyList(),
    val isSavingOnboarding: Boolean = false,
    val isLoading: Boolean = true,
    val errorMessage: String? = null,
) {
    val unreadNotificationCount: Int
        get() = notifications.count { !it.read }

    val securityActionCount: Int
        get() = vulnerabilityAlerts.count { it.status == VulnerabilityStatus.OPEN }
}

class BulletFeedViewModel(
    private val repository: BulletFeedRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(BulletFeedUiState())
    val uiState: StateFlow<BulletFeedUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching {
                val events = async { repository.getFeedEvents() }
                val alerts = async { repository.getVulnerabilityAlerts() }
                val notifications = async { repository.getNotifications() }
                val githubConnection = async { repository.getGithubConnection() }
                val onboarding = async { repository.getOnboardingSnapshot() }
                val onboardingSnapshot = onboarding.await()
                BulletFeedUiState(
                    events = events.await(),
                    vulnerabilityAlerts = alerts.await(),
                    notifications = notifications.await(),
                    githubConnected = githubConnection.await(),
                    onboardingCompleted = onboardingSnapshot.completed,
                    profile = onboardingSnapshot.profile,
                    topics = onboardingSnapshot.topics,
                    isLoading = false,
                )
            }.onSuccess { loadedState ->
                _uiState.value = loadedState
            }.onFailure {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        errorMessage = "情報を読み込めませんでした。通信状態を確認して再試行してください。",
                    )
                }
            }
        }
    }

    fun updateEventFeedback(
        eventId: String,
        feedback: Feedback,
    ) = launchUpdate {
        val current = _uiState.value.events.firstOrNull { it.id == eventId }
        val updated =
            if (feedback == Feedback.READ && current != null) {
                repository.markFeedItemRead(current.feedItemId)
            } else {
                repository.updateEventFeedback(eventId, feedback)
            }
        _uiState.update { state ->
            state.copy(events = state.events.replaceById(updated.id, updated) { it.id })
        }
    }

    fun toggleFollowing(eventId: String) =
        launchUpdate {
            val event = _uiState.value.events.firstOrNull { it.id == eventId } ?: return@launchUpdate
            val updated = repository.setFollowing(eventId, !event.following)
            _uiState.update { state ->
                state.copy(events = state.events.replaceById(updated.id, updated) { it.id })
            }
        }

    fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ) = launchUpdate {
        val updated = repository.updateVulnerabilityStatus(alertId, status)
        _uiState.update { state ->
            state.copy(
                vulnerabilityAlerts = state.vulnerabilityAlerts.replaceById(updated.id, updated) { it.id },
            )
        }
    }

    fun markNotificationRead(notificationId: String) =
        launchUpdate {
            val updated = repository.markNotificationRead(notificationId)
            _uiState.update { state ->
                state.copy(notifications = state.notifications.replaceById(updated.id, updated) { it.id })
            }
        }

    fun markAllNotificationsRead() =
        launchUpdate {
            val updated = repository.markAllNotificationsRead()
            _uiState.update { it.copy(notifications = updated) }
        }

    fun connectGithub() =
        launchUpdate {
            val connected = repository.setGithubConnected(true)
            _uiState.update { it.copy(githubConnected = connected) }
        }

    fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ) {
        _uiState.update { it.copy(isSavingOnboarding = true, errorMessage = null) }
        viewModelScope.launch {
            runCatching {
                repository.completeOnboarding(profile, topics, connectGithub)
            }.onSuccess { snapshot ->
                _uiState.update {
                    it.copy(
                        onboardingCompleted = snapshot.completed,
                        profile = snapshot.profile,
                        topics = snapshot.topics,
                        githubConnected = connectGithub,
                        isSavingOnboarding = false,
                    )
                }
            }.onFailure {
                _uiState.update {
                    it.copy(
                        isSavingOnboarding = false,
                        errorMessage = "初期設定を保存できませんでした。もう一度お試しください。",
                    )
                }
            }
        }
    }

    fun addTopic(name: String) =
        launchUpdate {
            val normalized = name.trim()
            if (normalized.isEmpty() || normalized in _uiState.value.topics) return@launchUpdate
            val updated = repository.updateTopics(_uiState.value.topics + normalized)
            _uiState.update { it.copy(topics = updated) }
        }

    fun removeTopic(name: String) =
        launchUpdate {
            val updated = repository.updateTopics(_uiState.value.topics - name)
            _uiState.update { it.copy(topics = updated) }
        }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }

    private fun launchUpdate(block: suspend () -> Unit) {
        viewModelScope.launch {
            runCatching { block() }.onFailure {
                _uiState.update { state ->
                    state.copy(errorMessage = "更新を保存できませんでした。もう一度お試しください。")
                }
            }
        }
    }

    companion object {
        val Factory: ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    require(modelClass.isAssignableFrom(BulletFeedViewModel::class.java))
                    @Suppress("UNCHECKED_CAST")
                    return BulletFeedViewModel(MockBulletFeedRepository()) as T
                }
            }
    }
}

private fun <T> List<T>.replaceById(
    id: String,
    replacement: T,
    idOf: (T) -> String,
): List<T> = map { item -> if (idOf(item) == id) replacement else item }
