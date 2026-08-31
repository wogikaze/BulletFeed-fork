package com.bulletfeed.app

import retrofit2.HttpException

class SessionRecoveryRequiredException : IllegalStateException("Existing BulletFeed user requires authentication recovery")

class RemoteBulletFeedRepository(
    private val api: BulletFeedApi,
    private val sessionManager: SessionManager,
) : BulletFeedRepository,
    FeedRepository by RemoteFeedRepository(api),
    EventRepository by RemoteEventRepository(api),
    MeRepository by RemoteMeRepository(api, sessionManager),
    IntegrationRepository by RemoteIntegrationRepository(api, sessionManager) {
    override suspend fun initialize() {
        if (sessionManager.accessToken != null) return
        if (sessionManager.refreshToken != null && recoverSession()) return
        if (sessionManager.userId == null) {
            createAndStoreSession()
            return
        }
        throw SessionRecoveryRequiredException()
    }

    override suspend fun recoverSession(): Boolean {
        val refreshToken = sessionManager.refreshToken ?: return false
        return try {
            storeSession(api.refreshSession(SessionRefreshDto(refreshToken)))
            true
        } catch (error: HttpException) {
            if (error.code() != 401) throw error
            sessionManager.clearAuthenticationTokens()
            false
        }
    }

    override suspend fun resetSession() {
        sessionManager.clearSession()
        createAndStoreSession()
    }

    private suspend fun createAndStoreSession() {
        storeSession(api.createSession())
    }

    private fun storeSession(session: SessionResponseDto) {
        sessionManager.accessToken = session.accessToken
        sessionManager.refreshToken = session.refreshToken
        sessionManager.userId = session.userId
    }

    override suspend fun getFeedEvents(): List<FeedEvent> =
        getFeedPage().items.map { it.toFeedEvent() }

    override suspend fun getGithubConnection(): Boolean = getGithubConnectionState().connected

    override suspend fun getOnboardingSnapshot(): OnboardingSnapshot {
        val me = getMe()
        val profile = getProfile()
        val topics = getUserTopics().map { it.name }
        return OnboardingSnapshot(
            completed = me.onboardingCompleted,
            state = me.onboardingState,
            profile = profile,
            topics = topics,
        )
    }

    override suspend fun updateTopics(topics: List<String>): List<String> {
        val current = getUserTopics()
        val toRemove = current.filter { it.name !in topics }
        val toAdd = topics.filter { name -> current.none { it.name == name } }
        toRemove.forEach { removeUserTopic(it.id) }
        toAdd.forEach { addUserTopic(it, TopicType.TECHNOLOGY) }
        return getUserTopics().map { it.name }
    }

    override suspend fun updateEventFeedback(
        eventId: String,
        feedback: Feedback,
    ) {
        val target = findFeedItemForEvent(eventId)
        when (val type = feedback.toFeedFeedbackType()) {
            null -> markFeedItemRead(target.id)
            else -> sendFeedFeedback(target.id, type)
        }
    }

    private suspend fun findFeedItemForEvent(eventId: String): FeedItem {
        var cursor: String? = null
        val seen = mutableSetOf<String>()
        do {
            val page = getFeedPage(cursor = cursor, limit = 50)
            page.items.firstOrNull { it.eventId == eventId }?.let { return it }
            val next = page.nextCursor
            if (next != null && !seen.add(next)) break
            cursor = next
        } while (cursor != null)
        error("Feed item not found for event $eventId")
    }

    override suspend fun setGithubConnected(connected: Boolean): Boolean {
        if (!connected) disconnectGithub()
        return getGithubConnectionState().connected
    }
}

class RemoteFeedRepository(
    private val api: BulletFeedApi,
) : FeedRepository {
    override suspend fun getFeedItems(): List<FeedItem> = getFeedPage().items

    override suspend fun getFeedPage(
        cursor: String?,
        limit: Int,
    ): FeedPage = api.getFeed(cursor = cursor, limit = limit).toDomain()

    override suspend fun getFilteredFeedPage(
        relation: Relation?,
        status: FeedItemStatus?,
        cursor: String?,
        limit: Int,
    ): FeedPage =
        api.getFeed(
            relation = relation?.name?.lowercase(),
            status = status?.name?.lowercase(),
            cursor = cursor,
            limit = limit,
        ).toDomain()

    override suspend fun markFeedItemRead(feedItemId: String) {
        api.markFeedItemRead(feedItemId)
    }

    override suspend fun sendFeedFeedback(
        feedItemId: String,
        type: FeedFeedbackType,
    ) {
        api.sendFeedFeedback(feedItemId, FeedbackDto(type.name.lowercase()))
    }

    override suspend fun recordExposures(items: List<FeedExposure>) {
        if (items.isEmpty()) return
        api.recordExposures(
            ExposuresDto(
                items.take(50).map { item ->
                    ExposureDto(
                        deliveryId = item.deliveryId,
                        displayedAt = item.displayedAt,
                        dwellMs = item.dwellMs,
                        visibleRatio = item.visibleRatio,
                        detailOpened = item.detailOpened,
                    )
                },
            ),
        )
    }

    override suspend fun startFeedSession(): FeedSessionTelemetry = api.startFeedSession().toDomain()

    override suspend fun endFeedSession(sessionId: String): FeedSessionTelemetry =
        api.endFeedSession(sessionId).toDomain()

    override suspend fun getFeedSessionMetrics(): FeedSessionMetrics = api.getFeedSessionMetrics().toDomain()
}

class RemoteEventRepository(
    private val api: BulletFeedApi,
) : EventRepository {
    override suspend fun getEventDetail(
        eventId: String,
        fromFeedItemId: String?,
    ): EventDetail = api.getEvent(eventId, fromFeedItemId).toDomain()

    override suspend fun setFollowing(
        eventId: String,
        following: Boolean,
    ): FeedEvent {
        val base = api.getFeed(limit = 50).items.firstOrNull { it.eventId == eventId }?.toDomain()?.toFeedEvent()
            ?: error("Feed context is required for the legacy setFollowing result")
        api.setFollowing(eventId, FollowingDto(following = following))
        return api.getEvent(eventId).toDomain().toFeedEvent(base)
    }

    override suspend fun updateFollowingDetail(
        eventId: String,
        following: Boolean,
    ): EventDetail {
        api.setFollowing(eventId, FollowingDto(following = following))
        return api.getEvent(eventId).toDomain()
    }
}

class RemoteMeRepository(
    private val api: BulletFeedApi,
    private val sessionManager: SessionManager,
) : MeRepository {
    override suspend fun getMe(): MeBootstrap = api.getMe().toDomain()

    override suspend fun deleteAccount() {
        api.deleteAccount()
        sessionManager.clearSession()
    }

    override suspend fun getProfile(): UserProfile = api.getProfile().toDomain()

    override suspend fun saveProfile(profile: UserProfile): UserProfile =
        api.updateProfile(profile.toDto()).toDomain()

    override suspend fun getUserTopics(): List<UserTopic> =
        api.getTopics().items.map { it.toDomain() }

    override suspend fun addUserTopic(
        name: String,
        type: TopicType,
    ): UserTopic = api.addTopic(TopicCreateDto(name, type.name.lowercase())).toDomain()

    override suspend fun removeUserTopic(topicId: String) {
        api.deleteTopic(topicId)
    }

    override suspend fun patchUserTopic(
        topicId: String,
        priority: TopicPriority?,
        order: Int?,
    ): UserTopic =
        api.patchTopic(
            topicId,
            TopicPatchDto(
                priority = priority?.name?.lowercase(),
                order = order,
            ),
        ).toDomain()

    override suspend fun searchTopics(query: String): List<UserTopic> =
        api.searchTopics(query).items.map { it.toDomain() }

    override suspend fun getTopicRecommendations(includeFollowed: Boolean): TopicRecommendationPage =
        api.getTopicRecommendations(includeFollowed = includeFollowed).toDomain()

    override suspend fun ignoreTopicRecommendation(topicId: String): TopicRecommendationPage =
        api.ignoreTopicRecommendation(topicId, TopicRecommendationDecisionDto("ignored")).toDomain()

    override suspend fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ): OnboardingSnapshot {
        val result = api.completeOnboarding(
            OnboardingDto(
                profile = profile.toDto(),
                topics = topics,
                connectGithub = connectGithub,
            ),
        )
        val persistedProfile = api.getProfile().toDomain()
        val persistedTopics = api.getTopics().items.map { it.toDomain().name }
        return OnboardingSnapshot(
            completed = result.completed,
            state = OnboardingState.valueOf(result.state.uppercase()),
            profile = persistedProfile,
            topics = persistedTopics,
        )
    }

    override suspend fun getSourceRecommendations(includeIgnored: Boolean): List<SourceRecommendation> =
        api.getSourceRecommendations(includeIgnored = includeIgnored).items.map { it.toDomain() }

    override suspend fun decideSourceRecommendation(
        candidateId: String,
        decision: SourceRecommendationDecision,
    ): SourceRecommendation =
        api.decideSourceRecommendation(
            candidateId,
            SourceRecommendationDecisionDto(decision.name.lowercase()),
        ).toDomain()

    override suspend fun getSourceSubscriptions(): List<SourceSubscription> =
        api.getSourceSubscriptions().items.map { it.toDomain() }

    override suspend fun addSourceSubscription(
        kind: UserSourceKind,
        url: String?,
        pageId: String?,
    ): SourceSubscription =
        api.addSourceSubscription(
            SourceSubscriptionCreateDto(
                kind = kind.name.lowercase(),
                url = url?.trim()?.takeIf { it.isNotEmpty() },
                pageId = pageId?.trim()?.takeIf { it.isNotEmpty() },
            ),
        ).toDomain()

    override suspend fun discoverSiteFeeds(url: String): SiteFeedDiscoverResult =
        api.discoverSiteFeeds(SiteFeedDiscoverRequestDto(url = url.trim())).toDomain()

    override suspend fun removeSourceSubscription(subscriptionId: String) {
        api.deleteSourceSubscription(subscriptionId)
    }

    override suspend fun getKnowledgeBootstrap(): KnowledgeBootstrapSummary =
        api.getKnowledgeBootstrap().toDomain()

    override suspend fun recordKnowledgeCheckpoint(
        subjectKind: BootstrapSubjectKind,
        subjectId: String,
        catchUp: Boolean,
        asOf: String?,
    ): KnowledgeBootstrapResult =
        api.putKnowledgeBootstrapCheckpoint(
            KnowledgeBootstrapCheckpointRequestDto(
                subjectKind = subjectKind.name.lowercase(),
                subjectId = subjectId,
                asOf = asOf,
                catchUp = catchUp,
            ),
        ).toDomain()

    override suspend fun recordExplicitKnowledgeClaims(claimIds: List<String>): KnowledgeBootstrapResult =
        api.postKnowledgeBootstrapClaims(KnowledgeBootstrapClaimsRequestDto(claimIds)).toDomain()

    override suspend fun resetKnowledgeBootstrap() {
        api.deleteKnowledgeBootstrap()
    }
}

class RemoteIntegrationRepository(
    private val api: BulletFeedApi,
    private val sessionManager: SessionManager,
) : IntegrationRepository {
    override suspend fun getGithubConnectionState(): GithubConnection = api.getGithubConnection().toDomain()

    override suspend fun startGithubAuthorization(): GithubAuthorization =
        persistAuthorization(api.authorizeGithub().toDomain())

    override suspend fun startGithubAccountRecovery(): GithubAuthorization =
        persistAuthorization(api.recoverSessionWithGithub().toDomain())

    private fun persistAuthorization(authorization: GithubAuthorization): GithubAuthorization {
        sessionManager.pendingGithubAuthorization =
            PendingGithubAuthorization(
                flowId = authorization.flowId,
                pollToken = authorization.pollToken,
                authorizationUrl = authorization.authorizationUrl,
                expiresAtMillis = System.currentTimeMillis() + authorization.expiresInSeconds * 1000L,
            )
        return authorization
    }

    override suspend fun pollGithubAuthorization(): GithubAuthorizationStatus? {
        val pending = sessionManager.pendingGithubAuthorization ?: return null
        if (pending.expiresAtMillis <= System.currentTimeMillis()) {
            sessionManager.pendingGithubAuthorization = null
            return GithubAuthorizationStatus(GithubAuthorizationState.EXPIRED)
        }
        val dto = try {
            api.getGithubAuthorizationStatus(pending.flowId, pending.pollToken)
        } catch (error: HttpException) {
            if (error.code() == 401 || error.code() == 404) {
                sessionManager.pendingGithubAuthorization = null
                return GithubAuthorizationStatus(
                    state = GithubAuthorizationState.FAILED,
                    detail = "GitHub authorization flow is no longer valid",
                )
            }
            throw error
        }
        val status = dto.toDomain()
        when (status.state) {
            GithubAuthorizationState.CONNECTED -> {
                val accessToken = dto.appAccessToken
                val refreshToken = dto.refreshToken
                if (accessToken.isNullOrBlank() || refreshToken.isNullOrBlank()) {
                    sessionManager.pendingGithubAuthorization = null
                    return GithubAuthorizationStatus(
                        state = GithubAuthorizationState.FAILED,
                        githubLogin = dto.githubLogin,
                        detail = "GitHub authorization completed without a refreshable app session",
                    )
                }
                sessionManager.accessToken = accessToken
                sessionManager.refreshToken = refreshToken
                sessionManager.pendingGithubAuthorization = null
            }
            GithubAuthorizationState.FAILED,
            GithubAuthorizationState.EXPIRED,
            -> sessionManager.pendingGithubAuthorization = null
            GithubAuthorizationState.PENDING -> Unit
        }
        return status
    }

    override suspend fun listGithubRepositories(query: String): List<GithubRepositoryChoice> =
        getGithubRepositoryPage(query = query).items

    override suspend fun getGithubRepositoryPage(
        query: String,
        cursor: String?,
        limit: Int,
    ): GithubRepositoryPage =
        api.listGithubRepositories(
            query = query.takeIf { it.isNotBlank() },
            cursor = cursor,
            limit = limit,
        ).toDomain()

    override suspend fun updateGithubRepositories(repositoryIds: List<String>): GithubTopicSyncResult =
        api.updateGithubRepositories(GithubRepositoryUpdateDto(repositoryIds.distinct())).toDomain()

    override suspend fun importFromPublicRepo(fullName: String): GithubTopicSyncResult =
        api.importRepositoryKeywords(GithubRepoImportDto(fullName)).toSyncResult()

    override suspend fun disconnectGithub() {
        api.disconnectGithub()
        sessionManager.pendingGithubAuthorization = null
    }

    override suspend fun getVulnerabilityAlerts(): List<VulnerabilityAlert> =
        api.getSecurityAlerts().items.map { it.toDomain() }

    override suspend fun getVulnerabilityAlert(alertId: String): VulnerabilityAlert =
        api.getSecurityAlert(alertId).toDomain()

    override suspend fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ): VulnerabilityAlert =
        api.patchSecurityAlert(alertId, SecurityAlertPatchDto(status.name.lowercase())).toDomain()

    override suspend fun getNotifications(): List<AppNotification> =
        api.getNotifications().items.map { it.toDomain() }

    override suspend fun markNotificationRead(notificationId: String): AppNotification =
        api.patchNotification(notificationId, NotificationReadDto(true)).toDomain()

    override suspend fun markAllNotificationsRead(): List<AppNotification> {
        api.readAllNotifications()
        return getNotifications()
    }
}
