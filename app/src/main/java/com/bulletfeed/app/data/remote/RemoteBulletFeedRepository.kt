package com.bulletfeed.app

class RemoteBulletFeedRepository(
    private val api: BulletFeedApi,
    private val sessionManager: SessionManager,
) : BulletFeedRepository,
    FeedRepository by RemoteFeedRepository(api),
    EventRepository by RemoteEventRepository(api),
    MeRepository by RemoteMeRepository(api),
    IntegrationRepository by RemoteIntegrationRepository(api) {
    override suspend fun initialize() {
        if (sessionManager.accessToken == null) {
            val session = api.createSession()
            sessionManager.accessToken = session.accessToken
            sessionManager.userId = session.userId
        }
    }

    override suspend fun getFeedEvents(): List<FeedEvent> =
        getFeedItems().map { it.toFeedEvent() }

    override suspend fun getGithubConnection(): Boolean = getGithubConnectionState().connected

    override suspend fun getOnboardingSnapshot(): OnboardingSnapshot {
        val me = getMe()
        val profile = getProfile()
        val topics = getUserTopics().map { it.name }
        return OnboardingSnapshot(
            completed = me.onboardingCompleted,
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
    ): FeedEvent {
        val feedItems = getFeedItems()
        val target = feedItems.firstOrNull { it.eventId == eventId }
            ?: error("Feed item not found for event $eventId")
        return when (feedback) {
            Feedback.READ -> markFeedItemRead(target.id)
            Feedback.IMPORTANT -> sendFeedFeedback(target.id, FeedFeedbackType.IMPORTANT)
            Feedback.NOT_RELEVANT -> sendFeedFeedback(target.id, FeedFeedbackType.NOT_RELEVANT)
        }
    }

    override suspend fun setGithubConnected(connected: Boolean): Boolean {
        if (!connected) {
            disconnectGithub()
        }
        return getGithubConnectionState().connected
    }
}

class RemoteFeedRepository(
    private val api: BulletFeedApi,
) : FeedRepository {
    override suspend fun getFeedItems(): List<FeedItem> =
        api.getFeed().items.map { it.toDomain() }

    override suspend fun markFeedItemRead(feedItemId: String): FeedEvent {
        val response = api.markFeedItemRead(feedItemId)
        val feedItems = getFeedItems()
        val item = feedItems.firstOrNull { it.id == response.feedItemId }
            ?: error("Feed item ${response.feedItemId} not found")
        return item.copy(status = FeedItemStatus.READ).toFeedEvent()
    }

    override suspend fun sendFeedFeedback(
        feedItemId: String,
        type: FeedFeedbackType,
    ): FeedEvent {
        val response = api.sendFeedFeedback(feedItemId, FeedbackDto(type.name.lowercase()))
        val feedItems = getFeedItems()
        val item = feedItems.firstOrNull { it.id == response.feedItemId }
            ?: error("Feed item ${response.feedItemId} not found")
        val updated = when (type) {
            FeedFeedbackType.IMPORTANT -> item.copy(markedImportant = true)
            FeedFeedbackType.NOT_RELEVANT ->
                item.copy(status = FeedItemStatus.READ, dismissed = true)
        }
        return updated.toFeedEvent()
    }

    override suspend fun recordExposures(items: List<FeedExposure>) {
        api.recordExposures(
            ExposuresDto(
                items.map { ExposureDto(it.deliveryId, it.displayedAt) },
            ),
        )
    }
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
        api.setFollowing(eventId, FollowingDto(following = following))
        return api.getEvent(eventId).toDomain().toFeedEvent()
    }
}

class RemoteMeRepository(
    private val api: BulletFeedApi,
) : MeRepository {
    override suspend fun getMe(): MeBootstrap = api.getMe().toDomain()

    override suspend fun getProfile(): UserProfile = api.getProfile().toDomain()

    override suspend fun saveProfile(profile: UserProfile): UserProfile =
        api.updateProfile(profile.toDto()).toDomain()

    override suspend fun getUserTopics(): List<UserTopic> =
        api.getTopics().items.map { it.toDomain() }

    override suspend fun addUserTopic(
        name: String,
        type: TopicType,
    ): UserTopic =
        api.addTopic(TopicCreateDto(name, type.name.lowercase())).toDomain()

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
        return OnboardingSnapshot(
            completed = result.completed,
            profile = profile,
            topics = topics,
        )
    }
}

class RemoteIntegrationRepository(
    private val api: BulletFeedApi,
) : IntegrationRepository {
    override suspend fun getGithubConnectionState(): GithubConnection = api.getGithubConnection().toDomain()

    override suspend fun startGithubAuthorization(): GithubAuthorization = api.authorizeGithub().toDomain()

    override suspend fun listGithubRepositories(query: String): List<GithubRepositoryChoice> =
        api.listGithubRepositories(query).items.map { it.toDomain() }

    override suspend fun updateGithubRepositories(repositoryIds: List<String>): GithubConnection =
        api.updateGithubRepositories(GithubRepositoryUpdateDto(repositoryIds)).toDomain()

    override suspend fun importFromPublicRepo(fullName: String): List<String> {
        val result = api.importRepositoryKeywords(GithubRepoImportDto(fullName))
        return result.addedTopics
    }

    override suspend fun disconnectGithub() {
        api.disconnectGithub()
    }

    override suspend fun getVulnerabilityAlerts(): List<VulnerabilityAlert> = api.getSecurityAlerts().items.map { it.toDomain() }

    override suspend fun getVulnerabilityAlert(alertId: String): VulnerabilityAlert = api.getSecurityAlert(alertId).toDomain()

    override suspend fun updateVulnerabilityStatus(
        alertId: String,
        status: VulnerabilityStatus,
    ): VulnerabilityAlert =
        api.patchSecurityAlert(alertId, SecurityAlertPatchDto(status.name.lowercase())).toDomain()

    override suspend fun getNotifications(): List<AppNotification> = api.getNotifications().items.map { it.toDomain() }

    override suspend fun markNotificationRead(notificationId: String): AppNotification = api.patchNotification(notificationId, NotificationReadDto(true)).toDomain()

    override suspend fun markAllNotificationsRead(): List<AppNotification> = api.readAllNotifications().let { getNotifications() }
}
