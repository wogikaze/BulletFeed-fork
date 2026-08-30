package com.bulletfeed.app

fun FeedItemDto.toDomain(): FeedItem =
    FeedItem(
        id = id,
        eventId = eventId,
        delta = delta.toDomain(),
        title = title,
        importance = importance.toDomain(),
        relation = relation.toDomain(),
        status = FeedItemStatus.valueOf(status.uppercase()),
        following = following,
        updatedAt = updatedAt,
        deliveryId = deliveryId,
        sources = sources.map { it.toDomain() },
        additionalSources = additionalSources.map { it.toDomain() },
    )

fun FeedPageDto.toDomain(): FeedPage = FeedPage(items = items.map { it.toDomain() }, nextCursor = nextCursor)

fun FeedSessionDto.toDomain(): FeedSessionTelemetry =
    FeedSessionTelemetry(version = version, id = id, startedAt = startedAt, endedAt = endedAt)

fun FeedSessionMetricsDto.toDomain(): FeedSessionMetrics =
    FeedSessionMetrics(
        version = version,
        sessionCount = sessionCount,
        displayedCount = displayedCount,
        usefulCardRate = usefulCardRate,
        alreadyKnownReshowRate = alreadyKnownReshowRate,
        cardsToUsefulItem = cardsToUsefulItem,
        feedbackResponseRate = feedbackResponseRate,
    )

fun FeedDeltaDto.toDomain(): FeedDelta =
    FeedDelta(
        id = id,
        type = DeltaType.valueOf(type.uppercase()),
        summary = summary,
        before = before,
        after = after,
        occurredAt = occurredAt,
    )

fun ImportanceDto.toDomain(): ImportanceInfo =
    ImportanceInfo(
        level = Importance.valueOf(level.uppercase()),
        reason = reason,
        confidence = confidence,
    )

fun RelationDto.toDomain(): RelationInfo =
    RelationInfo(
        level = Relation.valueOf(level.uppercase()),
        reason = reason,
        matchedTopics = matchedTopics,
        matchedRepositories = matchedRepositories.map { it.toDomain() },
    )

fun MatchedRepositoryDto.toDomain(): MatchedRepository = MatchedRepository(id = id, name = name, url = url)

fun EventDetailDto.toDomain(): EventDetail =
    EventDetail(
        id = id,
        title = title,
        summary = summary,
        currentState = currentState.toDomain(),
        latestDelta = latestDelta.toDomain(),
        openedDelta = openedDelta?.toDomain(),
        timeline = timeline.map { it.toDomain() },
        impacts = impacts.map { it.toDomain() },
        sources = sources.map { it.toDomain() },
        following = following,
    )

fun CurrentStateDto.toDomain(): CurrentState =
    CurrentState(
        phase = phase,
        summary = summary,
        since = since,
        confidence = confidence,
    )

fun EventTimelineEntryDto.toDomain(): EventTimelineEntry =
    EventTimelineEntry(
        id = id,
        type = TimelineType.valueOf(type.uppercase()),
        occurredAt = occurredAt,
        title = title,
        description = description,
        deltaId = deltaId,
        stateBefore = state?.get("before"),
        stateAfter = state?.get("after"),
    )

fun EventImpactDto.toDomain(): EventImpact = EventImpact(kind = kind, text = text, confidence = confidence)

fun EventSourceDto.toDomain(): EventSource =
    EventSource(
        publisher = publisher,
        kind = SourceKind.valueOf(kind.uppercase()),
        title = title,
        url = url,
        publishedAt = publishedAt,
        retrievedAt = retrievedAt,
        evidence = evidence,
    )

fun MeDto.toDomain(): MeBootstrap =
    MeBootstrap(
        onboardingCompleted = onboardingCompleted,
        onboardingState = OnboardingState.valueOf(onboardingState.uppercase()),
        profile = profile.toDomain(),
        topicCount = topicCount,
        githubConnected = githubConnected,
    )

fun ProfileDto.toDomain(): UserProfile = UserProfile(role = occupation, interests = interests.toSet(), region = region)

fun UserProfile.toDto(): ProfileDto = ProfileDto(occupation = role, interests = interests.toList(), region = region)

fun TopicRecommendationListDto.toDomain(): TopicRecommendationPage =
    TopicRecommendationPage(
        version = version,
        items = items.map { it.toDomain() },
        abstentions = abstentions.map { it.toDomain() },
        policyVersion = policyVersion,
        cohort = cohort,
    )

fun TopicRecommendationDto.toDomain(): TopicRecommendation =
    TopicRecommendation(
        id = id,
        name = name,
        type = runCatching { TopicType.valueOf(type.uppercase()) }.getOrDefault(TopicType.TECHNOLOGY),
        score = score,
        reason = reason,
        provenance = provenance,
        alreadyFollowed = alreadyFollowed,
        confidence = confidence,
        sourceSignals = sourceSignals,
    )

fun TopicRecommendationAbstentionDto.toDomain(): TopicRecommendationAbstention =
    TopicRecommendationAbstention(name = name, reason = reason, score = score)

fun TopicDto.toDomain(): UserTopic =
    UserTopic(
        id = id,
        name = name,
        type = TopicType.valueOf(type.uppercase()),
        priority = TopicPriority.valueOf(priority.uppercase()),
        order = order,
    )

fun GithubConnectionDto.toDomain(): GithubConnection =
    GithubConnection(
        connected = connected,
        credentialState = GithubCredentialState.valueOf(credentialState.uppercase()),
        accountLogin = accountLogin,
    )

fun GithubRepositoryUpdateResultDto.toDomain(): GithubTopicSyncResult =
    GithubTopicSyncResult(
        connection = GithubConnection(
            connected = connected,
            credentialState = GithubCredentialState.valueOf(credentialState.uppercase()),
            accountLogin = accountLogin,
        ),
        addedTopics = addedTopics,
        alreadyTrackedTopics = alreadyTrackedTopics,
        inspectedRepositoryCount = inspectedRepositoryCount,
        failedRepositoryCount = failedRepositoryCount,
    )

fun GithubImportResultDto.toSyncResult(): GithubTopicSyncResult =
    GithubTopicSyncResult(
        connection = GithubConnection(connected = false),
        addedTopics = addedTopics,
        inspectedRepositoryCount = 1,
        failedRepositoryCount = if (addedTopics.isEmpty() && keywords.isEmpty()) 1 else 0,
    )

fun GithubRepositoryDto.toDomain(): GithubRepositoryChoice =
    GithubRepositoryChoice(
        id = id,
        fullName = fullName,
        htmlUrl = htmlUrl,
        selected = selected,
        isPrivate = isPrivate,
        description = description,
        language = language,
        updatedAt = updatedAt,
    )

fun GithubRepositoryPageDto.toDomain(): GithubRepositoryPage =
    GithubRepositoryPage(items = items.map { it.toDomain() }, nextCursor = nextCursor)

fun GithubAuthorizeDto.toDomain(): GithubAuthorization =
    GithubAuthorization(
        authorizationUrl = authorizationUrl,
        flowId = flowId,
        pollToken = pollToken,
        expiresInSeconds = expiresInSeconds,
    )

fun GithubAuthorizationStatusDto.toDomain(): GithubAuthorizationStatus =
    GithubAuthorizationStatus(
        state = GithubAuthorizationState.valueOf(status.uppercase()),
        githubLogin = githubLogin,
        detail = detail,
    )

fun GithubImportResultDto.toDomain(): List<String> = addedTopics

fun SecurityAlertDto.toDomain(): VulnerabilityAlert =
    VulnerabilityAlert(
        id = id,
        advisoryId = advisoryId,
        cve = cve,
        title = title,
        summary = summary,
        severity = VulnerabilitySeverity.valueOf(severity.uppercase()),
        status = VulnerabilityStatus.valueOf(status.uppercase()),
        repository = repository.fullName,
        packageName = packageInfo.name,
        currentVersion = packageInfo.currentVersion,
        fixedVersion = packageInfo.fixedVersion,
        dependencyType = DependencyType.fromApi(packageInfo.dependencyType),
        detectedAt = detectedAt,
        source = source,
        evidence = evidence,
        recommendation = recommendation,
        cvssScore = cvssScore,
        dependencyTypeRaw = packageInfo.dependencyType,
    )

fun SourceRecommendationDto.toDomain(): SourceRecommendation =
    SourceRecommendation(
        id = id,
        endpointId = endpointId,
        canonicalUrl = canonicalUrl,
        family = family,
        discoveryMethod = discoveryMethod,
        discoveryProvenance = discoveryProvenance,
        verificationStatus = verificationStatus,
        authorityStatus = authorityStatus,
        authorityConfidence = authorityConfidence,
        evidenceEligible = evidenceEligible,
        discoveryOnly = discoveryOnly,
        reason = reason,
        explanation = explanation,
        matchedConcepts = matchedConcepts,
        matchOrigin = matchOrigin,
        matchKind = matchKind,
        score = score,
        recommendationStatus = SourceRecommendationStatus.valueOf(recommendationStatus.uppercase()),
        actionability = SourceActionability.valueOf(actionability.uppercase()),
        publisher = publisher?.toDomain(),
    )

fun SourcePublisherDto.toDomain(): SourcePublisher = SourcePublisher(slug = slug, displayName = displayName)

fun SourceSubscriptionDto.toDomain(): SourceSubscription =
    SourceSubscription(
        id = id,
        kind = kind,
        canonicalUrl = canonicalUrl,
        pageId = pageId,
        publisher = publisher?.toDomain(),
        selected = status?.selected ?: true,
        state = SourceSubscriptionState.valueOf((status?.state ?: "pending").uppercase()),
        lastSuccessAt = status?.lastSuccessAt,
        lastAttemptAt = status?.lastAttemptAt,
        failureCount = status?.failureCount ?: 0,
    )

fun KnowledgeBootstrapSummaryDto.toDomain(): KnowledgeBootstrapSummary =
    KnowledgeBootstrapSummary(
        version = version,
        explicitKnownFactCount = explicitClaimIds.size,
        inferredFactCount = inferredClaimIds.size,
        checkpoints = checkpoints.map { it.toDomain() },
        evidence = evidence.map { it.toDomain() },
    )

fun KnowledgeBootstrapCheckpointItemDto.toDomain(): KnowledgeBootstrapCheckpoint =
    KnowledgeBootstrapCheckpoint(
        subjectKind = BootstrapSubjectKind.valueOf(subjectKind.uppercase()),
        subjectId = subjectId,
        asOf = asOf,
        catchUp = catchUp,
        knownFactCount = claimIds.size,
    )

fun KnowledgeBootstrapEvidenceDto.toDomain(): KnowledgeBootstrapEvidence =
    KnowledgeBootstrapEvidence(
        id = id,
        kind = kind,
        provenance = provenance,
        confidence = confidence,
        sourceId = sourceId,
        eventId = eventId,
        createdAt = createdAt,
    )

fun KnowledgeBootstrapCheckpointResponseDto.toDomain(): KnowledgeBootstrapResult =
    KnowledgeBootstrapResult(
        version = version,
        subjectKind = BootstrapSubjectKind.valueOf(subjectKind.uppercase()),
        subjectId = subjectId,
        asOf = asOf,
        catchUp = catchUp,
        knownFactCount = claimIds.size,
    )

fun KnowledgeBootstrapClaimsResponseDto.toDomain(): KnowledgeBootstrapResult =
    KnowledgeBootstrapResult(
        version = version,
        sessionId = sessionId,
        knownFactCount = claimIds.size,
    )

fun NotificationDto.toDomain(): AppNotification =
    AppNotification(
        id = id,
        title = title,
        summary = summary,
        category = NotificationCategory.valueOf(category.uppercase()),
        priority = NotificationPriority.valueOf(priority.uppercase()),
        occurredAt = occurredAt,
        targetType = NotificationTargetType.fromApi(target.type),
        targetId = target.id,
        read = read,
        targetTypeRaw = target.type,
    )
