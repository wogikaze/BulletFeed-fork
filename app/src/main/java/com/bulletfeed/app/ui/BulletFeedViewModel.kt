package com.bulletfeed.app

import android.content.Context
import android.os.SystemClock
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

data class BulletFeedUiState(
    val events: List<FeedEvent> = emptyList(),
    val feedFilter: FeedFilter = FeedFilter.ALL,
    val feedDeliveryIds: Map<String, String> = emptyMap(),
    val feedNextCursor: String? = null,
    val isFeedLoadingMore: Boolean = false,
    val isFeedFiltering: Boolean = false,
    val feedLoadMoreError: String? = null,
    val eventDetailId: String? = null,
    val eventDetail: EventDetail? = null,
    val isEventDetailLoading: Boolean = false,
    val eventDetailError: String? = null,
    val vulnerabilityAlerts: List<VulnerabilityAlert> = emptyList(),
    val vulnerabilityDetailId: String? = null,
    val vulnerabilityDetail: VulnerabilityAlert? = null,
    val isVulnerabilityDetailLoading: Boolean = false,
    val vulnerabilityDetailError: String? = null,
    val notifications: List<AppNotification> = emptyList(),
    val githubConnection: GithubConnection = GithubConnection(false),
    val githubRepositories: List<GithubRepositoryChoice> = emptyList(),
    val githubNextCursor: String? = null,
    val githubQuery: String = "",
    val isGithubRepositoriesLoading: Boolean = false,
    val isGithubLoadingMore: Boolean = false,
    val isGithubSaving: Boolean = false,
    val githubRepositoryError: String? = null,
    val isGithubAuthorizing: Boolean = false,
    val githubTopicSyncMessage: String? = null,
    val onboardingCompleted: Boolean = false,
    val onboardingState: OnboardingState = OnboardingState.PROFILE,
    val profile: UserProfile = UserProfile("", emptySet(), ""),
    val isSavingProfile: Boolean = false,
    val topics: List<String> = emptyList(),
    val topicItems: List<UserTopic> = emptyList(),
    val topicSearchResults: List<UserTopic> = emptyList(),
    val topicSearchQuery: String = "",
    val isTopicSearchLoading: Boolean = false,
    val pendingGithubAuthUrl: String? = null,
    val isSavingOnboarding: Boolean = false,
    val isDeletingAccount: Boolean = false,
    val sourceRecommendations: List<SourceRecommendation> = emptyList(),
    val decidingRecommendationId: String? = null,
    val sourceSubscriptions: List<SourceSubscription> = emptyList(),
    val isSavingSourceSubscription: Boolean = false,
    val sourceSubscriptionError: String? = null,
    val knowledgeBootstrap: KnowledgeBootstrapSummary = KnowledgeBootstrapSummary(
        version = "",
        explicitKnownFactCount = 0,
        inferredFactCount = 0,
    ),
    val knowledgeBootstrapPrompt: KnowledgeBootstrapPrompt? = null,
    val isSavingKnowledgeBootstrap: Boolean = false,
    val topicRecommendations: List<TopicRecommendation> = emptyList(),
    val topicRecommendationCohort: String = "",
    val isLoading: Boolean = true,
    val sessionExpired: Boolean = false,
    val isOffline: Boolean = false,
    val hasStaleFeed: Boolean = false,
    val errorMessage: String? = null,
) {
    val githubConnected: Boolean
        get() = githubConnection.connected

    val githubReauthorizationRequired: Boolean
        get() = githubConnection.credentialState == GithubCredentialState.REAUTHORIZATION_REQUIRED

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

    private var refreshJob: Job? = null
    private var loadMoreFeedJob: Job? = null
    private var filterFeedJob: Job? = null
    private var eventDetailJob: Job? = null
    private var vulnerabilityDetailJob: Job? = null
    private var githubRepositoryJob: Job? = null
    private var githubAuthorizationJob: Job? = null
    private var topicSearchJob: Job? = null
    private var refreshVersion = 0L
    private var feedRequestVersion = 0L
    private var eventDetailVersion = 0L
    private var vulnerabilityDetailVersion = 0L
    private var githubRepositoryVersion = 0L
    private var topicSearchVersion = 0L
    private val activeEventMutations = mutableSetOf<String>()
    private val githubSelectionEdits = mutableMapOf<String, Boolean>()
    private val recordedExposureDeliveryIds = mutableSetOf<String>()
    private val pendingExposureDeliveryIds = mutableSetOf<String>()
    private val pendingExposureFeedItemIds = mutableMapOf<String, String>()
    private val viewportTracker = ViewportExposureTracker(nowMs = { SystemClock.elapsedRealtime() })
    private var lastViewportSnapshots: List<ViewportItemSnapshot> = emptyList()
    private var dwellRecheckJob: Job? = null
    private var telemetrySessionId: String? = null
    private var telemetryStartJob: Job? = null

    init {
        refresh()
    }

    fun refresh() {
        val version = ++refreshVersion
        ++feedRequestVersion
        loadMoreFeedJob?.cancel()
        filterFeedJob?.cancel()
        refreshJob?.cancel()
        refreshJob = viewModelScope.launch {
            _uiState.update { it.beginRefresh() }
            try {
                repository.initialize()
                val pendingAuthorization = runCatching { repository.pollGithubAuthorization() }.getOrNull()
                val onboarding = repository.getOnboardingSnapshot()
                val topicItems = repository.getUserTopics().sortedBy { it.order }
                val githubConnection = repository.getGithubConnectionState()

                val ready = onboarding.state == OnboardingState.READY
                var softError: String? = null
                val feedPage = if (ready) {
                    repository.getFilteredFeedPage(relation = _uiState.value.feedFilter.toRelationOrNull())
                } else {
                    FeedPage(emptyList(), null)
                }
                val alerts = if (ready) {
                    try {
                        repository.getVulnerabilityAlerts()
                    } catch (error: Throwable) {
                        softError = error.rememberSoftSubsystemError(softError)
                        emptyList()
                    }
                } else {
                    emptyList()
                }
                val notifications = if (ready) {
                    try {
                        repository.getNotifications()
                    } catch (error: Throwable) {
                        softError = error.rememberSoftSubsystemError(softError)
                        emptyList()
                    }
                } else {
                    emptyList()
                }
                val recommendations = if (ready) {
                    try {
                        repository.getSourceRecommendations()
                    } catch (error: Throwable) {
                        softError = error.rememberSoftSubsystemError(softError)
                        emptyList()
                    }
                } else {
                    emptyList()
                }
                val subscriptions = if (ready) {
                    try {
                        repository.getSourceSubscriptions()
                    } catch (error: Throwable) {
                        softError = error.rememberSoftSubsystemError(softError)
                        emptyList()
                    }
                } else {
                    emptyList()
                }
                val topicRecs = try {
                    repository.getTopicRecommendations(includeFollowed = false)
                } catch (error: Throwable) {
                    softError = error.rememberSoftSubsystemError(softError)
                    TopicRecommendationPage("", emptyList(), emptyList(), "", "")
                }
                val bootstrap = if (ready) {
                    try {
                        repository.getKnowledgeBootstrap()
                    } catch (error: Throwable) {
                        softError = error.rememberSoftSubsystemError(softError)
                        KnowledgeBootstrapSummary(version = "", explicitKnownFactCount = 0, inferredFactCount = 0)
                    }
                } else {
                    KnowledgeBootstrapSummary(version = "", explicitKnownFactCount = 0, inferredFactCount = 0)
                }
                if (version != refreshVersion) return@launch
                _uiState.update { current ->
                    current.copy(
                        events = feedPage.items.map { it.toFeedEvent() },
                        feedDeliveryIds = feedPage.deliveryIdMap(),
                        feedNextCursor = feedPage.nextCursor,
                        isFeedLoadingMore = false,
                        isFeedFiltering = false,
                        vulnerabilityAlerts = alerts,
                        notifications = notifications,
                        sourceRecommendations = recommendations,
                        sourceSubscriptions = subscriptions,
                        knowledgeBootstrap = bootstrap,
                        topicRecommendations = topicRecs.items,
                        topicRecommendationCohort = topicRecs.cohort,
                        githubConnection = githubConnection,
                        githubRepositories = if (githubConnection.credentialState == GithubCredentialState.REAUTHORIZATION_REQUIRED) {
                            emptyList()
                        } else {
                            current.githubRepositories
                        },
                        githubNextCursor = if (githubConnection.credentialState == GithubCredentialState.REAUTHORIZATION_REQUIRED) {
                            null
                        } else {
                            current.githubNextCursor
                        },
                        onboardingCompleted = onboarding.completed,
                        onboardingState = onboarding.state,
                        profile = onboarding.profile,
                        topics = topicItems.map { it.name },
                        topicItems = topicItems,
                        isLoading = false,
                        sessionExpired = false,
                        isOffline = false,
                        hasStaleFeed = false,
                        errorMessage = softError,
                    )
                }
                if (pendingAuthorization?.state == GithubAuthorizationState.PENDING) {
                    _uiState.update { it.copy(isGithubAuthorizing = true) }
                    startGithubAuthorizationPolling()
                }
                if (ready) {
                    startFeedTelemetrySession()
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version == refreshVersion) handleRootFailure(error)
            }
        }
    }

    /**
     * Recover the existing BulletFeed identity. This intentionally never creates a new anonymous user.
     * A refresh token is preferred; if it cannot be used, GitHub identity recovery is offered.
     */
    fun startNewSession() {
        if (_uiState.value.isGithubAuthorizing) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, sessionExpired = false, errorMessage = null) }
            try {
                if (repository.recoverSession()) {
                    clearExposureTracking()
                    refresh()
                    return@launch
                }
                startGithubAccountRecovery()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        sessionExpired = true,
                        errorMessage = error.toUserMessage(),
                    )
                }
            }
        }
    }

    fun setFeedFilter(filter: FeedFilter) {
        val state = _uiState.value
        if (state.onboardingState != OnboardingState.READY) return
        if (state.feedFilter == filter && !state.isFeedFiltering) return
        val version = ++feedRequestVersion
        loadMoreFeedJob?.cancel()
        filterFeedJob?.cancel()
        filterFeedJob = viewModelScope.launch {
            _uiState.update {
                it.copy(
                    feedFilter = filter,
                    isFeedFiltering = true,
                    feedLoadMoreError = null,
                )
            }
            try {
                val page = repository.getFilteredFeedPage(relation = filter.toRelationOrNull())
                if (version != feedRequestVersion) return@launch
                _uiState.update {
                    it.copy(
                        events = page.items.map { item -> item.toFeedEvent() },
                        feedDeliveryIds = page.deliveryIdMap(),
                        feedNextCursor = page.nextCursor,
                        isFeedFiltering = false,
                        isFeedLoadingMore = false,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version != feedRequestVersion) return@launch
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update {
                        it.copy(
                            isFeedFiltering = false,
                            feedLoadMoreError = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun loadMoreFeed() {
        val state = _uiState.value
        val cursor = state.feedNextCursor ?: return
        if (state.isFeedLoadingMore || state.isFeedFiltering || state.onboardingState != OnboardingState.READY) return
        val version = ++feedRequestVersion
        loadMoreFeedJob?.cancel()
        loadMoreFeedJob = viewModelScope.launch {
            _uiState.update { it.copy(isFeedLoadingMore = true, feedLoadMoreError = null) }
            try {
                val page = repository.getFilteredFeedPage(
                    relation = state.feedFilter.toRelationOrNull(),
                    cursor = cursor,
                )
                if (version != feedRequestVersion) return@launch
                val incoming = page.items.map { it.toFeedEvent() }
                val repeatedCursor = page.nextCursor != null && page.nextCursor == cursor
                _uiState.update { current ->
                    current.copy(
                        events = mergeFeedEvents(current.events, incoming),
                        feedDeliveryIds = current.feedDeliveryIds + page.deliveryIdMap(),
                        feedNextCursor = if (repeatedCursor) null else page.nextCursor,
                        isFeedLoadingMore = false,
                        feedLoadMoreError = if (repeatedCursor) "ページングcursorが進まなかったため読み込みを停止しました。" else null,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version != feedRequestVersion) return@launch
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update {
                        it.copy(
                            isFeedLoadingMore = false,
                            feedLoadMoreError = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun recordFeedViewportSnapshots(items: List<ViewportItemSnapshot>) {
        lastViewportSnapshots = items
        postMeaningfulExposures(viewportTracker.onSnapshots(items))
        scheduleDwellRecheck()
    }

    private fun scheduleDwellRecheck() {
        dwellRecheckJob?.cancel()
        val dueAt = viewportTracker.nextDueAtMs() ?: return
        dwellRecheckJob = viewModelScope.launch {
            delay((dueAt - SystemClock.elapsedRealtime()).coerceAtLeast(0L))
            postMeaningfulExposures(viewportTracker.onSnapshots(lastViewportSnapshots))
            scheduleDwellRecheck()
        }
    }

    private fun postMeaningfulExposures(ready: List<MeaningfulViewportExposure>) {
        if (ready.isEmpty()) return
        val deliveryByFeedItem = _uiState.value.feedDeliveryIds
        val displayedAt = currentUtcTimestamp()
        val exposures = mutableListOf<FeedExposure>()
        val deliveryIds = mutableListOf<String>()
        ready.forEach { item ->
            val deliveryId = deliveryByFeedItem[item.feedItemId] ?: return@forEach
            if (deliveryId in recordedExposureDeliveryIds || deliveryId in pendingExposureDeliveryIds) {
                return@forEach
            }
            deliveryIds += deliveryId
            pendingExposureFeedItemIds[deliveryId] = item.feedItemId
            exposures +=
                FeedExposure(
                    deliveryId = deliveryId,
                    displayedAt = displayedAt,
                    dwellMs = item.dwellMs,
                    visibleRatio = item.visibleRatio,
                    detailOpened = item.detailOpened,
                )
        }
        val limited = exposures.take(50)
        val limitedIds = deliveryIds.take(50)
        if (limited.isEmpty()) return
        pendingExposureDeliveryIds += limitedIds
        viewModelScope.launch {
            try {
                repository.recordExposures(limited)
                pendingExposureDeliveryIds.removeAll(limitedIds.toSet())
                recordedExposureDeliveryIds += limitedIds
                limitedIds.forEach { pendingExposureFeedItemIds.remove(it) }
            } catch (error: CancellationException) {
                pendingExposureDeliveryIds.removeAll(limitedIds.toSet())
                viewportTracker.allowRetry(limitedIds.mapNotNull { pendingExposureFeedItemIds.remove(it) })
                throw error
            } catch (error: Throwable) {
                // Failed knownness writes must remain retryable when the same items are visible again.
                pendingExposureDeliveryIds.removeAll(limitedIds.toSet())
                viewportTracker.allowRetry(limitedIds.mapNotNull { pendingExposureFeedItemIds.remove(it) })
                if (error.isUnauthorized()) handleRootFailure(error)
            }
        }
    }

    fun loadEventDetail(
        eventId: String,
        fromFeedItemId: String? = null,
    ) {
        fromFeedItemId?.let { feedItemId ->
            postMeaningfulExposures(listOf(viewportTracker.onDetailOpened(feedItemId)))
        }
        val version = ++eventDetailVersion
        eventDetailJob?.cancel()
        eventDetailJob = viewModelScope.launch {
            _uiState.update { current ->
                current.copy(
                    eventDetailId = eventId,
                    eventDetail = current.eventDetail.takeIf { current.eventDetailId == eventId },
                    isEventDetailLoading = true,
                    eventDetailError = null,
                )
            }
            try {
                val detail = repository.getEventDetail(eventId, fromFeedItemId)
                if (version != eventDetailVersion) return@launch
                _uiState.update {
                    it.copy(
                        eventDetailId = eventId,
                        eventDetail = detail,
                        isEventDetailLoading = false,
                        eventDetailError = null,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version != eventDetailVersion) return@launch
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    val inaccessible = error.httpCode() == 403 || error.httpCode() == 404
                    _uiState.update { current ->
                        current.copy(
                            events = if (inaccessible) current.events.filterNot { it.id == eventId } else current.events,
                            eventDetailId = eventId,
                            eventDetail = null,
                            isEventDetailLoading = false,
                            eventDetailError = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun clearEventDetail() {
        ++eventDetailVersion
        eventDetailJob?.cancel()
        _uiState.update {
            it.copy(eventDetailId = null, eventDetail = null, isEventDetailLoading = false, eventDetailError = null)
        }
    }

    fun loadVulnerabilityDetail(alertId: String) {
        val version = ++vulnerabilityDetailVersion
        vulnerabilityDetailJob?.cancel()
        vulnerabilityDetailJob = viewModelScope.launch {
            _uiState.update { current ->
                current.copy(
                    vulnerabilityDetailId = alertId,
                    vulnerabilityDetail = current.vulnerabilityDetail.takeIf { current.vulnerabilityDetailId == alertId },
                    isVulnerabilityDetailLoading = true,
                    vulnerabilityDetailError = null,
                )
            }
            try {
                val detail = repository.getVulnerabilityAlert(alertId)
                if (version != vulnerabilityDetailVersion) return@launch
                _uiState.update { current ->
                    current.copy(
                        vulnerabilityAlerts = replaceOrAppend(current.vulnerabilityAlerts, detail) { it.id },
                        vulnerabilityDetailId = alertId,
                        vulnerabilityDetail = detail,
                        isVulnerabilityDetailLoading = false,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version != vulnerabilityDetailVersion) return@launch
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    val inaccessible = error.httpCode() == 403 || error.httpCode() == 404
                    _uiState.update { current ->
                        current.copy(
                            vulnerabilityAlerts = if (inaccessible) current.vulnerabilityAlerts.filterNot { it.id == alertId } else current.vulnerabilityAlerts,
                            vulnerabilityDetailId = alertId,
                            vulnerabilityDetail = null,
                            isVulnerabilityDetailLoading = false,
                            vulnerabilityDetailError = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun clearVulnerabilityDetail() {
        ++vulnerabilityDetailVersion
        vulnerabilityDetailJob?.cancel()
        _uiState.update {
            it.copy(
                vulnerabilityDetailId = null,
                vulnerabilityDetail = null,
                isVulnerabilityDetailLoading = false,
                vulnerabilityDetailError = null,
            )
        }
    }

    fun updateEventFeedback(
        eventId: String,
        feedback: Feedback,
    ) {
        val event = _uiState.value.events.firstOrNull { it.id == eventId } ?: return
        launchEventMutation(eventId) {
            when (val type = feedback.toFeedFeedbackType()) {
                null -> repository.markFeedItemRead(event.feedItemId)
                else -> repository.sendFeedFeedback(event.feedItemId, type)
            }
            reloadFeedFromServer()
        }
    }

    fun toggleFollowing(eventId: String) {
        val detail = _uiState.value.eventDetail.takeIf { _uiState.value.eventDetailId == eventId }
        val currentFollowing = detail?.following ?: _uiState.value.events.firstOrNull { it.id == eventId }?.following ?: false
        launchEventMutation(eventId) {
            val updatedDetail = repository.updateFollowingDetail(eventId, !currentFollowing)
            _uiState.update { current ->
                val prompt =
                    if (!currentFollowing) {
                        KnowledgeBootstrapPrompt(
                            subjectKind = BootstrapSubjectKind.EVENT,
                            subjectId = eventId,
                            title = updatedDetail.title,
                            currentStateSummary = updatedDetail.currentState.summary,
                        )
                    } else {
                        current.knowledgeBootstrapPrompt
                    }
                if (current.eventDetailId == eventId) {
                    current.copy(eventDetail = updatedDetail, knowledgeBootstrapPrompt = prompt)
                } else {
                    current.copy(knowledgeBootstrapPrompt = prompt)
                }
            }
            reloadFeedFromServer()
        }
    }

    fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ) = launchUpdate {
        val updated = repository.updateVulnerabilityStatus(alertId, status)
        _uiState.update { state ->
            state.copy(
                vulnerabilityAlerts = replaceOrAppend(state.vulnerabilityAlerts, updated) { it.id },
                vulnerabilityDetail = if (state.vulnerabilityDetailId == alertId) updated else state.vulnerabilityDetail,
            )
        }
    }

    fun markNotificationRead(notificationId: String) = launchUpdate {
        val updated = repository.markNotificationRead(notificationId)
        _uiState.update { state ->
            state.copy(notifications = replaceOrAppend(state.notifications, updated) { it.id })
        }
    }

    fun markAllNotificationsRead() = launchUpdate {
        val updated = repository.markAllNotificationsRead()
        _uiState.update { it.copy(notifications = updated) }
    }

    fun connectGithub() {
        if (_uiState.value.isGithubAuthorizing) return
        viewModelScope.launch {
            _uiState.update { it.copy(isGithubAuthorizing = true, errorMessage = null) }
            try {
                val auth = repository.startGithubAuthorization()
                _uiState.update { it.copy(pendingGithubAuthUrl = auth.authorizationUrl) }
                startGithubAuthorizationPolling()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update {
                        it.copy(isGithubAuthorizing = false, errorMessage = error.toUserMessage())
                    }
                }
            }
        }
    }

    private fun startGithubAuthorizationPolling() {
        if (githubAuthorizationJob?.isActive == true) return
        githubAuthorizationJob = viewModelScope.launch {
            while (true) {
                delay(1_500)
                try {
                    val status = repository.pollGithubAuthorization()
                    if (status == null) {
                        _uiState.update { it.copy(isGithubAuthorizing = false) }
                        return@launch
                    }
                    when (status.state) {
                        GithubAuthorizationState.PENDING -> Unit
                        GithubAuthorizationState.CONNECTED -> {
                            _uiState.update { it.copy(isGithubAuthorizing = false) }
                            clearExposureTracking()
                            refresh()
                            return@launch
                        }
                        GithubAuthorizationState.FAILED,
                        GithubAuthorizationState.EXPIRED,
                        -> {
                            if (status.state == GithubAuthorizationState.FAILED &&
                                status.detail.isGithubIdentityConflict()
                            ) {
                                // The anonymous user's normal connect flow cannot claim an
                                // identity that already belongs to another account. Restart
                                // automatically with the existing-account recovery flow.
                                _uiState.update {
                                    it.copy(
                                        isGithubAuthorizing = false,
                                        pendingGithubAuthUrl = null,
                                        errorMessage = null,
                                    )
                                }
                                // This polling job is finishing now; allow the recovery
                                // flow to create its own polling job immediately.
                                githubAuthorizationJob = null
                                startGithubAccountRecovery()
                                return@launch
                            }
                            _uiState.update {
                                it.copy(
                                    isGithubAuthorizing = false,
                                    errorMessage = status.detail ?: "GitHub連携を完了できませんでした。もう一度認可してください。",
                                )
                            }
                            return@launch
                        }
                    }
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Throwable) {
                    _uiState.update {
                        it.copy(
                            isGithubAuthorizing = false,
                            errorMessage = error.toUserMessage(),
                        )
                    }
                    return@launch
                }
            }
        }
    }

    fun clearPendingAuthUrl() {
        _uiState.update { it.copy(pendingGithubAuthUrl = null) }
    }

    private fun startGithubAccountRecovery() {
        viewModelScope.launch {
            try {
                val authorization = repository.startGithubAccountRecovery()
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        sessionExpired = false,
                        isGithubAuthorizing = true,
                        pendingGithubAuthUrl = authorization.authorizationUrl,
                        errorMessage = null,
                    )
                }
                startGithubAuthorizationPolling()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        sessionExpired = true,
                        isGithubAuthorizing = false,
                        errorMessage = error.toUserMessage(),
                    )
                }
            }
        }
    }

    private fun String?.isGithubIdentityConflict(): Boolean =
        this?.contains("GitHub identity is already linked to another BulletFeed account", ignoreCase = true) == true

    fun loadGithubRepositories(
        query: String = _uiState.value.githubQuery,
        reset: Boolean = true,
    ) {
        val state = _uiState.value
        if (!state.githubConnected) return
        if (state.githubReauthorizationRequired) {
            _uiState.update {
                it.copy(
                    githubRepositories = emptyList(),
                    githubNextCursor = null,
                    isGithubRepositoriesLoading = false,
                    isGithubLoadingMore = false,
                    githubRepositoryError = "GitHubの認証情報が失効しています。再認証してください。",
                )
            }
            return
        }
        val version = ++githubRepositoryVersion
        githubRepositoryJob?.cancel()
        githubRepositoryJob = viewModelScope.launch {
            _uiState.update {
                it.copy(
                    githubQuery = query,
                    isGithubRepositoriesLoading = reset,
                    isGithubLoadingMore = !reset,
                    githubRepositoryError = null,
                )
            }
            try {
                val cursor = if (reset) null else _uiState.value.githubNextCursor
                if (!reset && cursor == null) {
                    _uiState.update { it.copy(isGithubLoadingMore = false) }
                    return@launch
                }
                val page = repository.getGithubRepositoryPage(query = query, cursor = cursor)
                if (version != githubRepositoryVersion) return@launch
                val editedItems = page.items.map { item ->
                    githubSelectionEdits[item.id]?.let { item.copy(selected = it) } ?: item
                }
                val repeatedCursor = !reset && page.nextCursor != null && page.nextCursor == cursor
                _uiState.update { current ->
                    current.copy(
                        githubRepositories = if (reset) editedItems else mergeRepositories(current.githubRepositories, editedItems),
                        githubNextCursor = if (repeatedCursor) null else page.nextCursor,
                        isGithubRepositoriesLoading = false,
                        isGithubLoadingMore = false,
                        githubRepositoryError = if (repeatedCursor) "ページングcursorが進まなかったため読み込みを停止しました。" else null,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version != githubRepositoryVersion) return@launch
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else if (error.httpCode() == 403) {
                    markGithubReauthorizationRequired()
                } else {
                    _uiState.update {
                        it.copy(
                            isGithubRepositoriesLoading = false,
                            isGithubLoadingMore = false,
                            githubRepositoryError = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun loadMoreGithubRepositories() = loadGithubRepositories(reset = false)

    fun toggleGithubRepository(repositoryId: String) {
        val item = _uiState.value.githubRepositories.firstOrNull { it.id == repositoryId } ?: return
        val selected = !item.selected
        githubSelectionEdits[repositoryId] = selected
        _uiState.update { current ->
            current.copy(
                githubRepositories = current.githubRepositories.map {
                    if (it.id == repositoryId) it.copy(selected = selected) else it
                },
            )
        }
    }

    fun saveGithubRepositories() {
        if (_uiState.value.isGithubSaving || _uiState.value.githubReauthorizationRequired) return
        viewModelScope.launch {
            _uiState.update { it.copy(isGithubSaving = true, githubRepositoryError = null, githubTopicSyncMessage = null) }
            try {
                val allRepositories = fetchAllGithubRepositories()
                val selectedIds = allRepositories
                    .filter { repository -> githubSelectionEdits[repository.id] ?: repository.selected }
                    .map { it.id }
                if (_uiState.value.onboardingState == OnboardingState.REPOSITORY_PENDING && selectedIds.isEmpty()) {
                    error("GitHub setup requires at least one selected repository")
                }
                val result = repository.updateGithubRepositories(selectedIds)
                githubSelectionEdits.clear()
                val onboarding = repository.getOnboardingSnapshot()
                val topicItems = repository.getUserTopics().sortedBy { it.order }
                val page = if (result.connection.credentialState == GithubCredentialState.CONNECTED) {
                    repository.getGithubRepositoryPage(query = _uiState.value.githubQuery)
                } else {
                    GithubRepositoryPage(emptyList(), null)
                }
                val feedPage = if (onboarding.state == OnboardingState.READY) {
                    repository.getFilteredFeedPage(relation = _uiState.value.feedFilter.toRelationOrNull())
                } else {
                    FeedPage(emptyList(), null)
                }
                val alerts = if (onboarding.state == OnboardingState.READY) repository.getVulnerabilityAlerts() else emptyList()
                _uiState.update { current ->
                    current.copy(
                        githubConnection = result.connection,
                        githubRepositories = page.items,
                        githubNextCursor = page.nextCursor,
                        isGithubSaving = false,
                        onboardingCompleted = onboarding.completed,
                        onboardingState = onboarding.state,
                        events = feedPage.items.map { it.toFeedEvent() },
                        feedDeliveryIds = feedPage.deliveryIdMap(),
                        feedNextCursor = feedPage.nextCursor,
                        vulnerabilityAlerts = alerts,
                        topicItems = topicItems,
                        topics = topicItems.map { topic -> topic.name },
                        githubTopicSyncMessage = githubTopicSyncMessage(result, selectedIds.size),
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else if (error.httpCode() == 403) {
                    markGithubReauthorizationRequired()
                } else {
                    _uiState.update {
                        it.copy(isGithubSaving = false, githubRepositoryError = error.toUserMessage())
                    }
                }
            }
        }
    }

    private suspend fun fetchAllGithubRepositories(): List<GithubRepositoryChoice> {
        val all = mutableListOf<GithubRepositoryChoice>()
        var cursor: String? = null
        val seenCursors = mutableSetOf<String>()
        do {
            val page = repository.getGithubRepositoryPage(query = "", cursor = cursor, limit = 50)
            all += page.items
            val next = page.nextCursor
            if (next != null && !seenCursors.add(next)) error("GitHub repository pagination cursor repeated")
            cursor = next
        } while (cursor != null)
        return all.distinctBy { it.id }
    }

    fun disconnectGithub() = launchUpdate {
        repository.disconnectGithub()
        githubSelectionEdits.clear()
        val connection = repository.getGithubConnectionState()
        val feedPage = if (_uiState.value.onboardingState == OnboardingState.READY) {
            repository.getFilteredFeedPage(relation = _uiState.value.feedFilter.toRelationOrNull())
        } else {
            FeedPage(emptyList(), null)
        }
        val alerts = if (_uiState.value.onboardingState == OnboardingState.READY) repository.getVulnerabilityAlerts() else emptyList()
        _uiState.update {
            it.copy(
                githubConnection = connection,
                githubRepositories = emptyList(),
                githubNextCursor = null,
                events = feedPage.items.map { item -> item.toFeedEvent() },
                feedDeliveryIds = feedPage.deliveryIdMap(),
                feedNextCursor = feedPage.nextCursor,
                vulnerabilityAlerts = alerts,
                githubTopicSyncMessage = null,
            )
        }
    }

    fun importFromPublicRepo(fullName: String) = launchUpdate {
        val result = repository.importFromPublicRepo(fullName)
        val connection = repository.getGithubConnectionState()
        val topicItems = repository.getUserTopics().sortedBy { it.order }
        _uiState.update { state ->
            state.copy(
                topics = topicItems.map { it.name },
                topicItems = topicItems,
                githubConnection = connection,
                githubTopicSyncMessage = githubTopicSyncMessage(
                    result.copy(connection = connection),
                    selectedRepositoryCount = 1,
                ),
            )
        }
        if (_uiState.value.onboardingState == OnboardingState.READY) reloadFeedFromServer()
    }

    fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ) {
        _uiState.update { it.copy(isSavingOnboarding = true, errorMessage = null) }
        viewModelScope.launch {
            try {
                val snapshot = repository.completeOnboarding(profile, topics, connectGithub)
                val topicItems = repository.getUserTopics().sortedBy { it.order }
                val connection = repository.getGithubConnectionState()
                _uiState.update {
                    it.copy(
                        onboardingCompleted = snapshot.completed,
                        onboardingState = snapshot.state,
                        profile = snapshot.profile,
                        topics = topicItems.map { item -> item.name },
                        topicItems = topicItems,
                        githubConnection = connection,
                        isSavingOnboarding = false,
                    )
                }
                when (snapshot.state) {
                    OnboardingState.GITHUB_PENDING -> connectGithub()
                    OnboardingState.READY -> reloadFeedFromServer()
                    OnboardingState.PROFILE,
                    OnboardingState.REPOSITORY_PENDING,
                    -> Unit
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update {
                        it.copy(
                            isSavingOnboarding = false,
                            errorMessage = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun saveProfile(profile: UserProfile) {
        if (_uiState.value.isSavingProfile) return
        viewModelScope.launch {
            _uiState.update { it.copy(isSavingProfile = true, errorMessage = null) }
            try {
                val saved = repository.saveProfile(profile)
                _uiState.update { it.copy(profile = saved, isSavingProfile = false) }
                reloadFeedFromServer()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update { it.copy(isSavingProfile = false, errorMessage = error.toUserMessage()) }
                }
            }
        }
    }

    fun deleteAccount() {
        if (_uiState.value.isDeletingAccount) return
        viewModelScope.launch {
            _uiState.update { it.copy(isDeletingAccount = true, errorMessage = null) }
            try {
                repository.deleteAccount()
                clearExposureTracking()
                repository.resetSession()
                refresh()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                _uiState.update { it.copy(isDeletingAccount = false, errorMessage = error.toUserMessage()) }
            }
        }
    }

    fun decideSourceRecommendation(
        candidateId: String,
        decision: SourceRecommendationDecision,
    ) {
        if (_uiState.value.decidingRecommendationId != null) return
        viewModelScope.launch {
            _uiState.update { it.copy(decidingRecommendationId = candidateId, errorMessage = null) }
            try {
                val updated = repository.decideSourceRecommendation(candidateId, decision)
                _uiState.update { current ->
                    val next =
                        current.sourceRecommendations
                            .map { if (it.id == updated.id) updated else it }
                            .filter { it.recommendationStatus != SourceRecommendationStatus.IGNORED }
                    current.copy(
                        sourceRecommendations = next,
                        decidingRecommendationId = null,
                    )
                }
                if (decision == SourceRecommendationDecision.APPROVED) {
                    refreshSourceSubscriptionsFromServer()
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update {
                        it.copy(
                            decidingRecommendationId = null,
                            errorMessage = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun addSourceSubscription(
        kind: UserSourceKind,
        url: String,
        pageId: String,
    ) {
        if (_uiState.value.isSavingSourceSubscription) return
        viewModelScope.launch {
            _uiState.update { it.copy(isSavingSourceSubscription = true, sourceSubscriptionError = null) }
            try {
                repository.addSourceSubscription(
                    kind = kind,
                    url = url.takeIf { kind != UserSourceKind.STATUSPAGE || it.isNotBlank() },
                    pageId = pageId.takeIf { kind == UserSourceKind.STATUSPAGE && it.isNotBlank() },
                )
                refreshSourceSubscriptionsFromServer()
                _uiState.update { it.copy(isSavingSourceSubscription = false, sourceSubscriptionError = null) }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update {
                        it.copy(
                            isSavingSourceSubscription = false,
                            sourceSubscriptionError = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun removeSourceSubscription(subscriptionId: String) {
        if (_uiState.value.isSavingSourceSubscription) return
        viewModelScope.launch {
            _uiState.update { it.copy(isSavingSourceSubscription = true, sourceSubscriptionError = null) }
            try {
                repository.removeSourceSubscription(subscriptionId)
                refreshSourceSubscriptionsFromServer()
                _uiState.update { it.copy(isSavingSourceSubscription = false) }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update {
                        it.copy(
                            isSavingSourceSubscription = false,
                            sourceSubscriptionError = error.toUserMessage(),
                        )
                    }
                }
            }
        }
    }

    fun addTopic(
        name: String,
        type: TopicType = TopicType.TECHNOLOGY,
    ) = launchUpdate {
        val normalized = name.trim()
        if (normalized.isEmpty() || _uiState.value.topicItems.any { it.name.equals(normalized, ignoreCase = true) }) return@launchUpdate
        if (_uiState.value.topicItems.size >= MAX_TRACKED_TOPICS) {
            showError(TOPIC_LIMIT_REACHED_MESSAGE)
            return@launchUpdate
        }
        val created = repository.addUserTopic(normalized, type)
        refreshTopicsFromServer()
        refreshTopicRecommendationsFromServer()
        refreshSourceRecommendationsFromServer()
        _uiState.update {
            it.copy(
                knowledgeBootstrapPrompt = KnowledgeBootstrapPrompt(
                    subjectKind = BootstrapSubjectKind.TOPIC,
                    subjectId = created.name,
                    title = created.name,
                    currentStateSummary = "このトピックに関する、いま真である現在状態だけを対象にできます。",
                ),
            )
        }
        reloadFeedFromServer()
    }

    fun removeTopic(topicId: String) = launchUpdate {
        repository.removeUserTopic(topicId)
        refreshTopicsFromServer()
        refreshTopicRecommendationsFromServer()
        refreshSourceRecommendationsFromServer()
        reloadFeedFromServer()
    }

    fun updateTopicPriority(
        topicId: String,
        priority: TopicPriority,
    ) = launchUpdate {
        repository.patchUserTopic(topicId, priority = priority)
        refreshTopicsFromServer()
        reloadFeedFromServer()
    }

    fun reorderTopics(orderedIds: List<String>) = launchUpdate {
        val current = _uiState.value.topicItems
        val currentById = current.associateBy { it.id }
        if (orderedIds == current.map { it.id }) return@launchUpdate
        val reordered = orderedIds.mapIndexedNotNull { index, id ->
            currentById[id]?.copy(order = index)
        }
        if (reordered.size != current.size) return@launchUpdate
        _uiState.update {
            it.copy(
                topicItems = reordered,
                topics = reordered.map { topic -> topic.name },
            )
        }
        reordered.forEach { topic ->
            val previous = currentById[topic.id] ?: return@forEach
            if (previous.order != topic.order) {
                repository.patchUserTopic(topic.id, order = topic.order)
            }
        }
        refreshTopicsFromServer()
        reloadFeedFromServer()
    }

    fun searchTopics(query: String) {
        val normalized = query.trim()
        val version = ++topicSearchVersion
        topicSearchJob?.cancel()
        _uiState.update { it.copy(topicSearchQuery = query) }
        if (normalized.isEmpty()) {
            _uiState.update { it.copy(topicSearchResults = emptyList(), isTopicSearchLoading = false) }
            return
        }
        topicSearchJob = viewModelScope.launch {
            _uiState.update { it.copy(isTopicSearchLoading = true) }
            try {
                val results = repository.searchTopics(normalized)
                if (version != topicSearchVersion) return@launch
                val selectedNames = _uiState.value.topicItems.mapTo(mutableSetOf()) { it.name.lowercase() }
                _uiState.update {
                    it.copy(
                        topicSearchResults = results.filterNot { result -> result.name.lowercase() in selectedNames },
                        isTopicSearchLoading = false,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (version != topicSearchVersion) return@launch
                if (error.isUnauthorized()) {
                    handleRootFailure(error)
                } else {
                    _uiState.update { it.copy(isTopicSearchLoading = false, errorMessage = error.toUserMessage()) }
                }
            }
        }
    }

    fun addTopicSearchResult(topic: UserTopic) = launchUpdate {
        if (_uiState.value.topicItems.any { it.name.equals(topic.name, ignoreCase = true) }) return@launchUpdate
        if (_uiState.value.topicItems.size >= MAX_TRACKED_TOPICS) {
            showError(TOPIC_LIMIT_REACHED_MESSAGE)
            return@launchUpdate
        }
        repository.addUserTopic(topic.name, topic.type)
        refreshTopicsFromServer()
        _uiState.update { state -> state.copy(topicSearchResults = state.topicSearchResults.filterNot { it.name == topic.name }) }
        reloadFeedFromServer()
    }

    fun showError(message: String) {
        _uiState.update { it.copy(errorMessage = message) }
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }

    private suspend fun refreshTopicsFromServer() {
        val items = repository.getUserTopics().sortedBy { it.order }
        _uiState.update {
            it.copy(
                topicItems = items,
                topics = items.map { item -> item.name },
            )
        }
    }

    fun ignoreTopicRecommendation(topicId: String) = launchUpdate {
        val page = repository.ignoreTopicRecommendation(topicId)
        _uiState.update {
            it.copy(
                topicRecommendations = page.items.filter { item -> !item.alreadyFollowed },
                topicRecommendationCohort = page.cohort,
            )
        }
    }

    fun addRecommendedTopic(item: TopicRecommendation) {
        addTopic(item.name, item.type)
    }

    fun dismissKnowledgeBootstrapPrompt() {
        _uiState.update { it.copy(knowledgeBootstrapPrompt = null) }
    }

    fun confirmKnowledgeAlreadyKnew() {
        val prompt = _uiState.value.knowledgeBootstrapPrompt ?: return
        recordKnowledgeCheckpoint(prompt, catchUp = false)
    }

    fun confirmKnowledgeCatchUpOnly() {
        val prompt = _uiState.value.knowledgeBootstrapPrompt ?: return
        recordKnowledgeCheckpoint(prompt, catchUp = true)
    }

    fun markEventCurrentStateKnown(eventId: String, catchUp: Boolean) {
        val detail = _uiState.value.eventDetail.takeIf { _uiState.value.eventDetailId == eventId }
        recordKnowledgeCheckpoint(
            KnowledgeBootstrapPrompt(
                subjectKind = BootstrapSubjectKind.EVENT,
                subjectId = eventId,
                title = detail?.title ?: eventId,
                currentStateSummary = detail?.currentState?.summary.orEmpty(),
            ),
            catchUp = catchUp,
        )
    }

    fun resetKnowledgeBootstrap() = launchUpdate {
        _uiState.update { it.copy(isSavingKnowledgeBootstrap = true) }
        try {
            repository.resetKnowledgeBootstrap()
            refreshKnowledgeBootstrapFromServer()
            reloadFeedFromServer()
            _uiState.update { it.copy(isSavingKnowledgeBootstrap = false) }
        } catch (error: Throwable) {
            _uiState.update { it.copy(isSavingKnowledgeBootstrap = false) }
            throw error
        }
    }

    private fun recordKnowledgeCheckpoint(
        prompt: KnowledgeBootstrapPrompt,
        catchUp: Boolean,
    ) = launchUpdate {
        _uiState.update { it.copy(isSavingKnowledgeBootstrap = true, errorMessage = null) }
        try {
            repository.recordKnowledgeCheckpoint(
                subjectKind = prompt.subjectKind,
                subjectId = prompt.subjectId,
                catchUp = catchUp,
            )
            refreshKnowledgeBootstrapFromServer()
            reloadFeedFromServer()
            _uiState.update {
                it.copy(
                    isSavingKnowledgeBootstrap = false,
                    knowledgeBootstrapPrompt = null,
                )
            }
        } catch (error: Throwable) {
            _uiState.update { it.copy(isSavingKnowledgeBootstrap = false) }
            throw error
        }
    }

    private suspend fun refreshKnowledgeBootstrapFromServer() {
        val summary = repository.getKnowledgeBootstrap()
        _uiState.update { it.copy(knowledgeBootstrap = summary) }
    }

    private suspend fun refreshTopicRecommendationsFromServer() {
        val page = repository.getTopicRecommendations(includeFollowed = false)
        _uiState.update {
            it.copy(
                topicRecommendations = page.items,
                topicRecommendationCohort = page.cohort,
            )
        }
    }

    private suspend fun refreshSourceRecommendationsFromServer() {
        val items = repository.getSourceRecommendations()
        _uiState.update { it.copy(sourceRecommendations = items) }
    }

    private suspend fun refreshSourceSubscriptionsFromServer() {
        val items = repository.getSourceSubscriptions()
        _uiState.update { it.copy(sourceSubscriptions = items) }
    }

    private fun markGithubReauthorizationRequired() {
        githubSelectionEdits.clear()
        _uiState.update { current ->
            current.copy(
                githubConnection = current.githubConnection.copy(
                    connected = true,
                    credentialState = GithubCredentialState.REAUTHORIZATION_REQUIRED,
                ),
                githubRepositories = emptyList(),
                githubNextCursor = null,
                isGithubRepositoriesLoading = false,
                isGithubLoadingMore = false,
                isGithubSaving = false,
                githubRepositoryError = "GitHubの認証情報が失効しています。再認証してください。",
            )
        }
    }

    private fun launchEventMutation(
        eventId: String,
        block: suspend () -> Unit,
    ) {
        if (!activeEventMutations.add(eventId)) return
        viewModelScope.launch {
            try {
                block()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) handleRootFailure(error) else showError(error.toUserMessage())
            } finally {
                activeEventMutations.remove(eventId)
            }
        }
    }

    private fun launchUpdate(block: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                block()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error.isUnauthorized()) handleRootFailure(error) else showError(error.toUserMessage())
            }
        }
    }

    private suspend fun reloadFeedFromServer() {
        if (_uiState.value.onboardingState != OnboardingState.READY) return
        val version = ++feedRequestVersion
        loadMoreFeedJob?.cancel()
        filterFeedJob?.cancel()
        val page = repository.getFilteredFeedPage(relation = _uiState.value.feedFilter.toRelationOrNull())
        if (version != feedRequestVersion) return
        _uiState.update {
            it.copy(
                events = page.items.map { item -> item.toFeedEvent() },
                feedDeliveryIds = page.deliveryIdMap(),
                feedNextCursor = page.nextCursor,
                isFeedLoadingMore = false,
                isFeedFiltering = false,
                feedLoadMoreError = null,
            )
        }
    }

    private fun clearExposureTracking() {
        recordedExposureDeliveryIds.clear()
        pendingExposureDeliveryIds.clear()
        pendingExposureFeedItemIds.clear()
        lastViewportSnapshots = emptyList()
        dwellRecheckJob?.cancel()
        viewportTracker.reset()
    }

    private fun handleRootFailure(error: Throwable) {
        _uiState.update { it.reduceRootFailure(error) }
    }

    fun startFeedTelemetrySession() {
        if (_uiState.value.onboardingState != OnboardingState.READY) return
        if (!telemetrySessionId.isNullOrBlank() || telemetryStartJob?.isActive == true) return
        telemetryStartJob = viewModelScope.launch {
            try {
                val session = repository.startFeedSession()
                telemetrySessionId = session.id.takeIf { it.isNotBlank() }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Throwable) {
                // Telemetry must not change feed UX.
            }
        }
    }

    fun endFeedTelemetrySession() {
        val sessionId = telemetrySessionId
        telemetrySessionId = null
        telemetryStartJob?.cancel()
        telemetryStartJob = null
        if (sessionId.isNullOrBlank()) return
        viewModelScope.launch {
            withContext(NonCancellable) {
                runCatching { repository.endFeedSession(sessionId) }
            }
        }
    }

    override fun onCleared() {
        endFeedTelemetrySession()
        super.onCleared()
    }

    class Factory(
        private val context: Context,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(BulletFeedViewModel::class.java))
            val (api, sessionManager) = BulletFeedApiFactory.create(context)
            return BulletFeedViewModel(RemoteBulletFeedRepository(api, sessionManager)) as T
        }
    }
}

internal fun BulletFeedUiState.beginRefresh(): BulletFeedUiState =
    copy(
        isLoading = true,
        sessionExpired = false,
        isOffline = false,
        hasStaleFeed = false,
        errorMessage = null,
        feedLoadMoreError = null,
    )

internal fun Throwable.rememberSoftSubsystemError(existing: String?): String {
    if (isUnauthorized() || this is SessionRecoveryRequiredException) throw this
    return existing ?: toUserMessage()
}

internal fun BulletFeedUiState.reduceRootFailure(error: Throwable): BulletFeedUiState {
    val unauthorized = error.isUnauthorized() || error is SessionRecoveryRequiredException
    return copy(
        events = if (unauthorized) emptyList() else events,
        feedDeliveryIds = if (unauthorized) emptyMap() else feedDeliveryIds,
        feedNextCursor = if (unauthorized) null else feedNextCursor,
        vulnerabilityAlerts = if (unauthorized) emptyList() else vulnerabilityAlerts,
        notifications = if (unauthorized) emptyList() else notifications,
        eventDetail = if (unauthorized) null else eventDetail,
        vulnerabilityDetail = if (unauthorized) null else vulnerabilityDetail,
        isLoading = false,
        isFeedLoadingMore = false,
        isFeedFiltering = false,
        sessionExpired = unauthorized,
        isOffline = !unauthorized && error is IOException,
        hasStaleFeed = !unauthorized && events.isNotEmpty(),
        errorMessage = if (unauthorized) null else error.toUserMessage(),
    )
}

internal fun FeedFilter.toRelationOrNull(): Relation? =
    when (this) {
        FeedFilter.ALL -> null
        FeedFilter.DIRECT -> Relation.DIRECT
        FeedFilter.ADJACENT -> Relation.ADJACENT
        FeedFilter.REFERENCE -> Relation.REFERENCE
    }

internal fun FeedPage.deliveryIdMap(): Map<String, String> = items.associate { it.id to it.deliveryId }

internal fun mergeFeedEvents(
    current: List<FeedEvent>,
    incoming: List<FeedEvent>,
): List<FeedEvent> {
    val seen = current.mapTo(linkedSetOf()) { it.feedItemId }
    return current + incoming.filter { seen.add(it.feedItemId) }
}

private fun mergeRepositories(
    current: List<GithubRepositoryChoice>,
    incoming: List<GithubRepositoryChoice>,
): List<GithubRepositoryChoice> {
    val seen = current.mapTo(linkedSetOf()) { it.id }
    return current + incoming.filter { seen.add(it.id) }
}

private fun <T> replaceOrAppend(
    current: List<T>,
    replacement: T,
    idOf: (T) -> String,
): List<T> {
    val id = idOf(replacement)
    return if (current.any { idOf(it) == id }) {
        current.map { if (idOf(it) == id) replacement else it }
    } else {
        current + replacement
    }
}

private fun currentUtcTimestamp(): String =
    SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }.format(Date())

private fun Throwable.httpCode(): Int? = (this as? HttpException)?.code()

private fun Throwable.isUnauthorized(): Boolean = httpCode() == 401

private fun Throwable.toUserMessage(): String {
    val apiValidationMessage = apiValidationMessage()
    return when {
        this is SessionRecoveryRequiredException -> "保存済みのBulletFeedアカウントへ再認証してください。"
        this is IOException -> "通信できませんでした。接続を確認して再試行してください。"
        httpCode() == 401 -> "認証の有効期限が切れました。同じアカウントへ再認証してください。"
        httpCode() == 403 ->
            apiValidationMessage
                ?: "この情報へのアクセス権がありません。GitHubの再認証または情報源の許可設定を確認してください。"
        httpCode() == 404 -> "対象は削除されたか、現在はアクセスできません。"
        apiValidationMessage != null -> apiValidationMessage
        httpCode() == 409 -> "サーバー上の状態が更新されています。再読み込みしてからやり直してください。"
        httpCode() == 422 -> "入力または要求がAPI契約を満たしていません。内容を確認してください。"
        httpCode() == 429 -> "リクエストが集中しています。少し後に再試行してください。"
        (httpCode() ?: 0) >= 500 -> serviceUnavailableMessage()
        else -> "処理を完了できませんでした。再試行してください。"
    }
}

private fun Throwable.serviceUnavailableMessage(): String {
    val detail = fastApiDetail()?.lowercase().orEmpty()
    return when {
        "worker" in detail || "heartbeat" in detail ->
            "情報源の同期ワーカーが応答していません。再試行してください。"
        "database" in detail ->
            "データベースの準備ができていません。再試行してください。"
        else -> "サーバーで処理できませんでした。再試行してください。"
    }
}

private fun Throwable.fastApiDetail(): String? {
    val httpError = this as? HttpException ?: return null
    val body = runCatching { httpError.response()?.errorBody()?.string() }.getOrNull() ?: return null
    return runCatching { apiErrorJson.decodeFromString<FastApiDetailEnvelope>(body).detail }
        .getOrNull()
        ?.takeIf { it.isNotBlank() }
}

private fun Throwable.apiValidationMessage(): String? {
    val httpError = this as? HttpException ?: return null
    if (httpError.code() !in setOf(403, 409, 422)) return null
    val body = runCatching { httpError.response()?.errorBody()?.string() }.getOrNull() ?: return null
    val raw = runCatching { apiErrorJson.decodeFromString<ApiErrorEnvelope>(body).error.message }.getOrNull()
    val message = raw?.removePrefix("Value error, ")?.trim()?.takeIf { it.isNotEmpty() }
    return when (message) {
        "topic limit reached" -> TOPIC_LIMIT_REACHED_MESSAGE
        "topic already exists" -> "すでに追跡中のテーマです。"
        "url is required" -> "URLを入力してください。"
        "Unsupported source kind" -> "この種類の情報源は購読できません。"
        "Invalid Statuspage ID" -> "Statuspage の page ID が正しくありません。"
        "pageId or url is required for statuspage" -> "Statuspage は page ID または URL が必要です。"
        "Statuspage URL must use a statuspage.io page host" -> "Statuspage は statuspage.io のページURLを指定してください。"
        "RSS fetching is disabled" -> "RSS/JSON Feed の取得は現在無効です。"
        "Web fetching is disabled" -> "Webページの取得は現在無効です。"
        "RSS host is not in the allowlist" -> "このホストのフィードは許可されていません。"
        "RSS host cannot be resolved" -> "フィードのホスト名を解決できません。"
        else -> message?.takeIf { it.isNotBlank() && it.length <= 180 }
    }
}

@Serializable
private data class FastApiDetailEnvelope(
    val detail: String? = null,
)

@Serializable
private data class ApiErrorEnvelope(
    val error: ApiErrorDetail,
)

@Serializable
private data class ApiErrorDetail(
    val message: String,
)

private val apiErrorJson = Json { ignoreUnknownKeys = true }

private const val TOPIC_LIMIT_REACHED_MESSAGE =
    "追跡できるテーマは最大${MAX_TRACKED_TOPICS}件です。別のテーマを1件削除してから追加してください。"

internal fun githubTopicSyncMessage(
    result: GithubTopicSyncResult,
    selectedRepositoryCount: Int,
): String {
    val added = result.addedTopics
    val alreadyTracked = result.alreadyTrackedTopics
    val failedAll = selectedRepositoryCount > 0 &&
        result.failedRepositoryCount >= selectedRepositoryCount &&
        added.isEmpty() &&
        alreadyTracked.isEmpty()
    return when {
        added.isNotEmpty() && alreadyTracked.isNotEmpty() ->
            "テーマに追加しました: ${added.joinToString("、")}\nすでに追跡中: ${alreadyTracked.joinToString("、")}"
        added.isNotEmpty() ->
            "テーマに追加しました: ${added.joinToString("、")}"
        alreadyTracked.isNotEmpty() ->
            "検出したテーマはすでに追跡中です: ${alreadyTracked.joinToString("、")}"
        failedAll ->
            "選択したrepositoryからテーマを読み取れませんでした。権限と接続を確認してください。"
        selectedRepositoryCount == 0 ->
            "監視するrepositoryを選ぶと、使っている技術がテーマに追加されます。"
        else ->
            "選択したrepositoryから新しいテーマは見つかりませんでした。"
    }
}
