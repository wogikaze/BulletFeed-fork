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
        displayReason = displayReason?.toDomain(),
    )

fun DisplayReasonDto.toDomain(): DisplayReason =
    DisplayReason(
        policyVersion = policyVersion,
        rankingPolicyVersion = rankingPolicyVersion,
        primaryCode = primaryCode,
        text = text,
        codes = codes,
        matchKind = matchKind,
        deltaKind = deltaKind,
        independentEvidenceCount = independentEvidenceCount.coerceAtLeast(1),
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
        unknownFacts = unknownFacts.map { it.toDomain() },
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

fun UnknownFactDto.toDomain(): UnknownFact = UnknownFact(id = id, text = text)

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
        reason = reason.toTopicRecommendationReason(name),
        provenance = provenance.toRecommendationProvenanceLabel(),
        alreadyFollowed = alreadyFollowed,
        confidence = confidence.toConfidenceLabel(),
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
        topicSyncState = topicSyncState.toGithubTopicSyncState(),
    )

fun GithubTopicSyncStatusDto.toDomain(): GithubTopicSyncStatus =
    GithubTopicSyncStatus(
        state = state.toGithubTopicSyncState(),
        addedTopics = addedTopics,
        alreadyTrackedTopics = alreadyTrackedTopics,
        inspectedRepositoryCount = inspectedRepositoryCount,
        failedRepositoryCount = failedRepositoryCount,
        error = error,
    )

private fun String.toGithubTopicSyncState(): GithubTopicSyncState =
    runCatching { GithubTopicSyncState.valueOf(uppercase()) }
        .getOrDefault(GithubTopicSyncState.COMPLETED)

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
        discoveryProvenance = discoveryProvenance.toDiscoveryProvenanceLabel(),
        verificationStatus = verificationStatus,
        authorityStatus = authorityStatus.toAuthorityStatusLabel(),
        authorityConfidence = authorityConfidence,
        evidenceEligible = evidenceEligible,
        discoveryOnly = discoveryOnly,
        reason = reason.toSourceRecommendationReason(),
        explanation = explanation.toSafeUserFacingExplanation(),
        matchedConcepts = matchedConcepts,
        matchOrigin = matchOrigin,
        matchKind = matchKind,
        score = score,
        recommendationStatus = SourceRecommendationStatus.valueOf(recommendationStatus.uppercase()),
        actionability = SourceActionability.valueOf(actionability.uppercase()),
        publisher = publisher?.toDomain(),
    )

fun SourcePublisherDto.toDomain(): SourcePublisher = SourcePublisher(slug = slug, displayName = displayName)

fun SiteFeedDiscoverItemDto.toDomain(): SiteFeedDiscoverItem =
    SiteFeedDiscoverItem(
        id = id,
        endpointId = endpointId,
        canonicalUrl = canonicalUrl,
        family = family,
        discoveryMethod = discoveryMethod,
        discoveryProvenance = discoveryProvenance,
        title = title,
        preferred = preferred,
        evidenceEligible = evidenceEligible,
        discoveryOnly = discoveryOnly,
        actionability = SourceActionability.valueOf(actionability.uppercase()),
        verificationStatus = verificationStatus,
        authorityStatus = authorityStatus,
        explanation = explanation.toSafeUserFacingExplanation(),
        siteUrl = siteUrl,
        publisher = publisher?.toDomain(),
    )

fun SiteFeedDiscoverResultDto.toDomain(): SiteFeedDiscoverResult =
    SiteFeedDiscoverResult(
        version = version,
        siteUrl = siteUrl,
        canonicalSiteUrl = canonicalSiteUrl,
        preferredFamily = preferredFamily,
        items = items.map { it.toDomain() },
    )

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

private fun String.toTopicRecommendationReason(topicName: String): String {
    val value = trim()
    return when {
        value.startsWith("Matches your explicit interest in ", ignoreCase = true) ->
            "${value.substringAfter(" in ").trim()} に関心があるため"
        value.startsWith("Inferred from ", ignoreCase = true) ->
            "利用状況から $topicName に関心があると推定したため"
        value.startsWith("Semantic neighbor of ", ignoreCase = true) ->
            "${value.substringAfter(" of ").trim()} と関連の深いテーマのため"
        value.startsWith("Appears in events related to your interests (", ignoreCase = true) ->
            "興味のある分野に関連する更新で $topicName が取り上げられているため"
        value.startsWith("Catalog fallback for ", ignoreCase = true) || value.equals("catalog fallback", ignoreCase = true) ->
            "まだ興味の情報が少ないため、人気のあるテーマから提案しています。"
        value.hasJapaneseText() -> value
        else -> "興味や利用状況との関連から提案しています。"
    }
}

private fun String.toSourceRecommendationReason(): String {
    val value = trim()
    return when {
        value.startsWith("Matches your explicit interest in ", ignoreCase = true) ->
            "${value.substringAfter(" in ").trim()} に関心があるため"
        value.startsWith("Matches your inferred interest in ", ignoreCase = true) ->
            "${value.substringAfter(" in ").trim()} に関心があると推定したため"
        value.startsWith("Related to your explicit interest via ", ignoreCase = true) ->
            "関心のある ${value.substringAfter(" via ").trim()} に関連するため"
        value.startsWith("Related to your inferred interest via ", ignoreCase = true) ->
            "${value.substringAfter(" via ").trim()} への関心があると推定され、関連性があるため"
        value.hasJapaneseText() -> value
        else -> "興味のある分野に関連する情報源です。"
    }
}

private fun String.toRecommendationProvenanceLabel(): String =
    when (trim().lowercase()) {
        "explicit" -> "設定した興味"
        "inferred" -> "利用状況から推定"
        "catalog" -> "テーマ一覧"
        else -> if (hasJapaneseText()) trim() else "自動推定"
    }

private fun String.toConfidenceLabel(): String =
    when (trim().lowercase()) {
        "high" -> "高"
        "medium" -> "中"
        "low" -> "低"
        else -> if (hasJapaneseText()) trim() else "未評価"
    }

private fun String.toDiscoveryProvenanceLabel(): String =
    when (trim().lowercase()) {
        "curated_seed" -> "登録済みの情報源"
        "repository_metadata" -> "GitHubリポジトリ"
        "website_feed", "site_html_link" -> "Webサイトのフィード"
        "statuspage_link" -> "ステータスページ"
        "sitemap_link" -> "サイトマップ"
        "package_homepage" -> "パッケージ情報"
        "external_index" -> "外部インデックス"
        else -> if (hasJapaneseText()) trim() else "自動検出"
    }

private fun String.toAuthorityStatusLabel(): String =
    when (trim().lowercase()) {
        "authoritative", "official" -> "公式"
        "non_authoritative" -> "非公式"
        "aggregator" -> "情報集約サイト"
        "unknown", "unverified" -> "未確認"
        else -> if (hasJapaneseText()) trim() else "未確認"
    }

private fun String.toSafeUserFacingExplanation(): String {
    val value = trim()
    return value.takeIf { it.hasJapaneseText() }.orEmpty()
}

private fun String.hasJapaneseText(): Boolean =
    any { character ->
        character in '\u3040'..'\u30FF' || character in '\u3400'..'\u9FFF'
    }
