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

fun MatchedRepositoryDto.toDomain(): MatchedRepository =
    MatchedRepository(id = id, name = name, url = url)

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
        phase = EventPhase.valueOf(phase.uppercase()),
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

fun EventImpactDto.toDomain(): EventImpact =
    EventImpact(kind = kind, text = text, confidence = confidence)

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
        profile = profile.toDomain(),
        topicCount = topicCount,
        githubConnected = githubConnected,
    )

fun ProfileDto.toDomain(): UserProfile =
    UserProfile(role = occupation, interests = interests.toSet(), region = region)

fun UserProfile.toDto(): ProfileDto =
    ProfileDto(occupation = role, interests = interests.toList(), region = region)

fun TopicDto.toDomain(): UserTopic =
    UserTopic(
        id = id,
        name = name,
        type = TopicType.valueOf(type.uppercase()),
        priority = TopicPriority.valueOf(priority.uppercase()),
        order = order,
    )

fun GithubConnectionDto.toDomain(): GithubConnection =
    GithubConnection(connected = connected, accountLogin = accountLogin)

fun GithubRepositoryDto.toDomain(): GithubRepositoryChoice =
    GithubRepositoryChoice(
        id = id,
        fullName = fullName,
        htmlUrl = htmlUrl,
        selected = selected,
    )

fun GithubAuthorizeDto.toDomain(): GithubAuthorization =
    GithubAuthorization(
        authorizationUrl = authorizationUrl,
        flowId = flowId,
        pollToken = pollToken,
        expiresInSeconds = expiresInSeconds,
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
        fixedVersion = packageInfo.fixedVersion.takeIf { it.isNotEmpty() },
        dependencyType = DependencyType.valueOf(packageInfo.dependencyType.uppercase()),
        detectedAt = detectedAt,
        source = source,
        evidence = evidence,
        recommendation = recommendation,
        cvssScore = cvssScore,
    )

fun NotificationDto.toDomain(): AppNotification =
    AppNotification(
        id = id,
        title = title,
        summary = summary,
        category = NotificationCategory.valueOf(category.uppercase()),
        priority = NotificationPriority.valueOf(priority.uppercase()),
        occurredAt = occurredAt,
        targetType = NotificationTargetType.valueOf(target.type.uppercase()),
        targetId = target.id,
        read = read,
    )
