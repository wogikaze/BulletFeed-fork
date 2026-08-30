package com.bulletfeed.app

class MockMeStore(
    private val state: MockAppState,
) : MeRepository {
    override suspend fun getMe(): MeBootstrap =
        MeBootstrap(
            onboardingCompleted = state.onboardingCompleted,
            onboardingState = if (state.onboardingCompleted) OnboardingState.READY else OnboardingState.PROFILE,
            profile = state.profile,
            topicCount = state.topics.size,
            githubConnected = state.github.connected,
        )

    override suspend fun getProfile(): UserProfile = state.profile

    override suspend fun saveProfile(profile: UserProfile): UserProfile {
        state.profile = profile
        return state.profile
    }

    override suspend fun getUserTopics(): List<UserTopic> = state.topics.toList()

    override suspend fun addUserTopic(
        name: String,
        type: TopicType,
    ): UserTopic {
        val topic =
            UserTopic(
                id = "topic_${state.topics.size}",
                name = name.trim(),
                type = type,
                priority = TopicPriority.NORMAL,
                order = state.topics.size,
            )
        state.topics += topic
        return topic
    }

    override suspend fun removeUserTopic(topicId: String) {
        state.topics.removeAll { it.id == topicId }
    }

    override suspend fun patchUserTopic(
        topicId: String,
        priority: TopicPriority?,
        order: Int?,
    ): UserTopic {
        val index = state.topics.indexOfFirst { it.id == topicId }
        val current = state.topics[index]
        val updated =
            current.copy(
                priority = priority ?: current.priority,
                order = order ?: current.order,
            )
        state.topics[index] = updated
        return updated
    }

    override suspend fun searchTopics(query: String): List<UserTopic> =
        state.topicCatalog.filter { it.name.contains(query, ignoreCase = true) }

    override suspend fun completeOnboarding(
        profile: UserProfile,
        topics: List<String>,
        connectGithub: Boolean,
    ): OnboardingSnapshot {
        state.profile = profile
        state.topics =
            topics
                .distinct()
                .mapIndexed { index, name ->
                    UserTopic("topic_$index", name, TopicType.TECHNOLOGY, TopicPriority.NORMAL, index)
                }.toMutableList()
        state.github = state.github.copy(connected = connectGithub)
        state.onboardingCompleted = true
        return OnboardingSnapshot(
            completed = true,
            state = OnboardingState.READY,
            profile = state.profile,
            topics = state.topicNames(),
        )
    }

    override suspend fun getSourceRecommendations(includeIgnored: Boolean): List<SourceRecommendation> =
        state.sourceRecommendations.filter { includeIgnored || it.recommendationStatus != SourceRecommendationStatus.IGNORED }

    override suspend fun decideSourceRecommendation(
        candidateId: String,
        decision: SourceRecommendationDecision,
    ): SourceRecommendation {
        val index = state.sourceRecommendations.indexOfFirst { it.id == candidateId }
        require(index >= 0) { "unknown recommendation" }
        val status =
            when (decision) {
                SourceRecommendationDecision.APPROVED -> SourceRecommendationStatus.APPROVED
                SourceRecommendationDecision.IGNORED -> SourceRecommendationStatus.IGNORED
            }
        val updated = state.sourceRecommendations[index].copy(recommendationStatus = status)
        state.sourceRecommendations[index] = updated
        return updated
    }

    override suspend fun getSourceSubscriptions(): List<SourceSubscription> = emptyList()
}
