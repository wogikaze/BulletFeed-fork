package com.bulletfeed.app

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.VerticalDivider
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.delay

@Composable
fun BulletFeedApp(
    deepLink: String? = null,
    viewModel: BulletFeedViewModel = viewModel(factory = BulletFeedViewModel.Factory(LocalContext.current)),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val lifecycleState by lifecycleOwner.lifecycle.currentStateFlow.collectAsStateWithLifecycle()
    var tabName by rememberSaveable { mutableStateOf(AppTab.FEED.name) }
    var selectedEventId by rememberSaveable { mutableStateOf<String?>(null) }
    var selectedFeedItemId by rememberSaveable { mutableStateOf<String?>(null) }
    var selectedVulnerabilityId by rememberSaveable { mutableStateOf<String?>(null) }
    var notificationsOpen by rememberSaveable { mutableStateOf(false) }
    var githubSetupOpen by rememberSaveable { mutableStateOf(false) }
    val tab = AppTab.entries.firstOrNull { it.name == tabName } ?: AppTab.FEED

    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            viewModel.refresh()
            viewModel.startFeedTelemetrySession()
            try {
                while (true) {
                    delay(60_000)
                    viewModel.refresh()
                }
            } finally {
                viewModel.endFeedTelemetrySession()
            }
        }
    }

    LaunchedEffect(uiState.pendingGithubAuthUrl, lifecycleState) {
        uiState.pendingGithubAuthUrl?.let { url ->
            if (!lifecycleState.isAtLeast(Lifecycle.State.RESUMED)) return@LaunchedEffect
            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
                .onFailure { viewModel.showError("GitHub認可画面を開けませんでした。") }
            viewModel.clearPendingAuthUrl()
        }
    }

    LaunchedEffect(deepLink) {
        val uri = deepLink?.let(Uri::parse) ?: return@LaunchedEffect
        notificationsOpen = false
        githubSetupOpen = false
        when (uri.host) {
            "oauth" -> {
                if (uri.pathSegments.firstOrNull() == "github") {
                    // The callback carries no credentials. The pending flow and poll token remain
                    // in protected local storage; refresh claims the completed flow immediately.
                    viewModel.refresh()
                }
            }
            "event",
            "security",
            -> {
                val id = uri.pathSegments.firstOrNull() ?: return@LaunchedEffect
                if (uri.host == "event") {
                    selectedVulnerabilityId = null
                    selectedEventId = id
                    selectedFeedItemId = null
                } else {
                    selectedEventId = null
                    selectedFeedItemId = null
                    selectedVulnerabilityId = id
                }
            }
        }
    }

    LaunchedEffect(selectedEventId, selectedFeedItemId) {
        selectedEventId?.let { viewModel.loadEventDetail(it, selectedFeedItemId) }
    }
    LaunchedEffect(selectedVulnerabilityId) {
        selectedVulnerabilityId?.let(viewModel::loadVulnerabilityDetail)
    }
    LaunchedEffect(
        githubSetupOpen,
        uiState.onboardingState,
        uiState.githubConnection.credentialState,
    ) {
        val shouldLoad = githubSetupOpen || uiState.onboardingState == OnboardingState.REPOSITORY_PENDING
        if (
            shouldLoad &&
            uiState.githubConnected &&
            uiState.githubConnection.credentialState == GithubCredentialState.CONNECTED
        ) {
            viewModel.loadGithubRepositories()
        }
    }

    MaterialTheme(colorScheme = bulletFeedColorScheme()) {
        Surface(modifier = Modifier.fillMaxSize()) {
            when {
                uiState.sessionExpired -> ReauthenticationScreen(
                    isAuthorizing = uiState.isGithubAuthorizing,
                    onReauthenticate = viewModel::startNewSession,
                )
                uiState.isLoading && uiState.onboardingState == OnboardingState.PROFILE && uiState.profile.role.isEmpty() -> AppLoadingScreen()
                uiState.onboardingState == OnboardingState.PROFILE ->
                    Box(Modifier.fillMaxSize()) {
                        OnboardingScreen(
                            initialProfile = uiState.profile,
                            initialTopics = uiState.topics,
                            isSaving = uiState.isSavingOnboarding,
                            onComplete = viewModel::completeOnboarding,
                            recommendedTopics = uiState.topicRecommendations,
                            onIgnoreRecommendation = viewModel::ignoreTopicRecommendation,
                        )
                        uiState.errorMessage?.let {
                            TransientErrorBanner(
                                it,
                                viewModel::clearError,
                                modifier = Modifier.align(Alignment.TopCenter),
                            )
                        }
                    }
                uiState.onboardingState == OnboardingState.GITHUB_PENDING ->
                    GithubAuthorizationRequiredScreen(
                        isAuthorizing = uiState.isGithubAuthorizing,
                        errorMessage = uiState.errorMessage,
                        onAuthorize = viewModel::connectGithub,
                    )
                uiState.onboardingState == OnboardingState.REPOSITORY_PENDING && uiState.githubReauthorizationRequired ->
                    GithubReauthorizationRequiredScreen(
                        accountLogin = uiState.githubConnection.accountLogin,
                        isAuthorizing = uiState.isGithubAuthorizing,
                        showBack = false,
                        onBack = {},
                        onAuthorize = viewModel::connectGithub,
                    )
                uiState.onboardingState == OnboardingState.REPOSITORY_PENDING ->
                    GithubConnectionScreen(
                        connection = uiState.githubConnection,
                        repositories = uiState.githubRepositories,
                        nextCursor = uiState.githubNextCursor,
                        query = uiState.githubQuery,
                        isLoading = uiState.isGithubRepositoriesLoading,
                        isLoadingMore = uiState.isGithubLoadingMore,
                        isSaving = uiState.isGithubSaving,
                        isAuthorizing = uiState.isGithubAuthorizing,
                        errorMessage = uiState.githubRepositoryError,
                        topicSyncMessage = uiState.githubTopicSyncMessage,
                        onBack = {},
                        onConnect = viewModel::connectGithub,
                        onSearch = { viewModel.loadGithubRepositories(query = it) },
                        onLoadMore = viewModel::loadMoreGithubRepositories,
                        onToggleRepository = viewModel::toggleGithubRepository,
                        onSaveRepositories = viewModel::saveGithubRepositories,
                        onImportRepo = viewModel::importFromPublicRepo,
                        onDisconnect = viewModel::disconnectGithub,
                    )
                uiState.onboardingState == OnboardingState.READY ->
                    ReadyApplication(
                        uiState = uiState,
                        tab = tab,
                        selectedEventId = selectedEventId,
                        selectedFeedItemId = selectedFeedItemId,
                        selectedVulnerabilityId = selectedVulnerabilityId,
                        notificationsOpen = notificationsOpen,
                        githubSetupOpen = githubSetupOpen,
                        isOffline = uiState.isOffline,
                        hasStaleFeed = uiState.hasStaleFeed,
                        onTabChange = { tabName = it.name },
                        onSelectEvent = { event ->
                            selectedVulnerabilityId = null
                            selectedEventId = event.id
                            selectedFeedItemId = event.feedItemId
                        },
                        onSelectEventTarget = { eventId ->
                            selectedVulnerabilityId = null
                            selectedEventId = eventId
                            selectedFeedItemId = null
                        },
                        onClearEvent = {
                            selectedEventId = null
                            selectedFeedItemId = null
                            viewModel.clearEventDetail()
                        },
                        onSelectVulnerability = {
                            selectedEventId = null
                            selectedFeedItemId = null
                            selectedVulnerabilityId = it.id
                        },
                        onSelectVulnerabilityTarget = { alertId ->
                            selectedEventId = null
                            selectedFeedItemId = null
                            selectedVulnerabilityId = alertId
                        },
                        onClearVulnerability = {
                            selectedVulnerabilityId = null
                            viewModel.clearVulnerabilityDetail()
                        },
                        onNotificationsChange = { notificationsOpen = it },
                        onGithubSetupChange = { githubSetupOpen = it },
                        onRetry = viewModel::refresh,
                        viewModel = viewModel,
                    )
                else -> AppLoadingScreen()
            }
        }
    }
}

@Composable
private fun ReadyApplication(
    uiState: BulletFeedUiState,
    tab: AppTab,
    selectedEventId: String?,
    selectedFeedItemId: String?,
    selectedVulnerabilityId: String?,
    notificationsOpen: Boolean,
    githubSetupOpen: Boolean,
    isOffline: Boolean,
    hasStaleFeed: Boolean,
    onTabChange: (AppTab) -> Unit,
    onSelectEvent: (FeedEvent) -> Unit,
    onSelectEventTarget: (String) -> Unit,
    onClearEvent: () -> Unit,
    onSelectVulnerability: (VulnerabilityAlert) -> Unit,
    onSelectVulnerabilityTarget: (String) -> Unit,
    onClearVulnerability: () -> Unit,
    onNotificationsChange: (Boolean) -> Unit,
    onGithubSetupChange: (Boolean) -> Unit,
    onRetry: () -> Unit,
    viewModel: BulletFeedViewModel,
) = Box(Modifier.fillMaxSize()) {
    val pane =
        AppReadyPane.resolve(
            widthDp = LocalConfiguration.current.screenWidthDp,
            tab = tab,
            selectedEventId = selectedEventId,
            selectedVulnerabilityId = selectedVulnerabilityId,
            notificationsOpen = notificationsOpen,
            githubSetupOpen = githubSetupOpen,
        )
    val mainNavigation: @Composable () -> Unit = {
        MainNavigation(
            uiState = uiState,
            tab = tab,
            onTabChange = onTabChange,
            onFilterChange = viewModel::setFeedFilter,
            onEventSelect = onSelectEvent,
            onVulnerabilitySelect = onSelectVulnerability,
            onNotificationsOpen = { onNotificationsChange(true) },
            onGithubSetupOpen = { onGithubSetupChange(true) },
            onEventFeedback = viewModel::updateEventFeedback,
            onFollow = viewModel::toggleFollowing,
            onAddTopic = viewModel::addTopic,
            onRemoveTopic = viewModel::removeTopic,
            onSearchTopics = viewModel::searchTopics,
            onAddTopicSearchResult = viewModel::addTopicSearchResult,
            onPriorityChange = viewModel::updateTopicPriority,
            onReorderTopics = viewModel::reorderTopics,
            onAddRecommendedTopic = viewModel::addRecommendedTopic,
            onIgnoreTopicRecommendation = viewModel::ignoreTopicRecommendation,
            onSaveProfile = viewModel::saveProfile,
            onDeleteAccount = viewModel::deleteAccount,
            onApproveRecommendation = { viewModel.decideSourceRecommendation(it, SourceRecommendationDecision.APPROVED) },
            onIgnoreRecommendation = { viewModel.decideSourceRecommendation(it, SourceRecommendationDecision.IGNORED) },
            onAddSubscription = viewModel::addSourceSubscription,
            onRemoveSubscription = viewModel::removeSourceSubscription,
            onDiscoverSiteFeeds = viewModel::discoverSiteFeeds,
            onResetKnowledgeBootstrap = viewModel::resetKnowledgeBootstrap,
            onResetLearnedRanking = viewModel::resetLearnedRanking,
            onLoadMoreFeed = viewModel::loadMoreFeed,
            onVisibleFeedItems = viewModel::recordFeedViewportSnapshots,
        )
    }
    when (pane) {
        AppReadyPane.EVENT_LIST_DETAIL -> {
            AppListDetailSplit(
                list = { mainNavigation() },
                detail = {
                    SelectedEventPane(
                        uiState = uiState,
                        selectedEventId = checkNotNull(selectedEventId),
                        selectedFeedItemId = selectedFeedItemId,
                        onClearEvent = onClearEvent,
                        viewModel = viewModel,
                    )
                },
            )
        }
        AppReadyPane.VULNERABILITY_LIST_DETAIL -> {
            AppListDetailSplit(
                list = { mainNavigation() },
                detail = {
                    SelectedVulnerabilityPane(
                        uiState = uiState,
                        selectedVulnerabilityId = checkNotNull(selectedVulnerabilityId),
                        onClearVulnerability = onClearVulnerability,
                        viewModel = viewModel,
                    )
                },
            )
        }
        AppReadyPane.EVENT_STACKED -> SelectedEventPane(
            uiState = uiState,
            selectedEventId = checkNotNull(selectedEventId),
            selectedFeedItemId = selectedFeedItemId,
            onClearEvent = onClearEvent,
            viewModel = viewModel,
        )
        AppReadyPane.VULNERABILITY_STACKED -> SelectedVulnerabilityPane(
            uiState = uiState,
            selectedVulnerabilityId = checkNotNull(selectedVulnerabilityId),
            onClearVulnerability = onClearVulnerability,
            viewModel = viewModel,
        )
        AppReadyPane.NOTIFICATIONS -> NotificationsScreen(
            notifications = uiState.notifications,
            onBack = { onNotificationsChange(false) },
            onNotificationClick = { notification ->
                viewModel.markNotificationRead(notification.id)
                onNotificationsChange(false)
                when (notification.targetType) {
                    NotificationTargetType.EVENT -> onSelectEventTarget(notification.targetId)
                    NotificationTargetType.VULNERABILITY -> onSelectVulnerabilityTarget(notification.targetId)
                    NotificationTargetType.UNKNOWN -> viewModel.showError(
                        "未対応の通知target type: ${notification.targetTypeRaw}",
                    )
                }
            },
            onMarkAllRead = viewModel::markAllNotificationsRead,
        )
        AppReadyPane.GITHUB -> {
            if (uiState.githubReauthorizationRequired) {
                GithubReauthorizationRequiredScreen(
                    accountLogin = uiState.githubConnection.accountLogin,
                    isAuthorizing = uiState.isGithubAuthorizing,
                    showBack = true,
                    onBack = {
                        onGithubSetupChange(false)
                        viewModel.refresh()
                    },
                    onAuthorize = viewModel::connectGithub,
                )
            } else {
                GithubConnectionScreen(
                    connection = uiState.githubConnection,
                    repositories = uiState.githubRepositories,
                    nextCursor = uiState.githubNextCursor,
                    query = uiState.githubQuery,
                    isLoading = uiState.isGithubRepositoriesLoading,
                    isLoadingMore = uiState.isGithubLoadingMore,
                    isSaving = uiState.isGithubSaving,
                    isAuthorizing = uiState.isGithubAuthorizing,
                    errorMessage = uiState.githubRepositoryError,
                    topicSyncMessage = uiState.githubTopicSyncMessage,
                    onBack = {
                        onGithubSetupChange(false)
                        viewModel.refresh()
                    },
                    onConnect = viewModel::connectGithub,
                    onSearch = { viewModel.loadGithubRepositories(query = it) },
                    onLoadMore = viewModel::loadMoreGithubRepositories,
                    onToggleRepository = viewModel::toggleGithubRepository,
                    onSaveRepositories = viewModel::saveGithubRepositories,
                    onImportRepo = viewModel::importFromPublicRepo,
                    onDisconnect = viewModel::disconnectGithub,
                )
            }
        }
        AppReadyPane.MAIN -> mainNavigation()
    }
    uiState.knowledgeBootstrapPrompt?.let { prompt ->
        KnowledgeBootstrapPromptDialog(
            prompt = prompt,
            isSaving = uiState.isSavingKnowledgeBootstrap,
            onAlreadyKnew = viewModel::confirmKnowledgeAlreadyKnew,
            onCatchUp = viewModel::confirmKnowledgeCatchUpOnly,
            onDismiss = viewModel::dismissKnowledgeBootstrapPrompt,
        )
    }
    if (isOffline) {
        OfflineRecoveryBanner(
            hasStaleFeed = hasStaleFeed,
            onRetry = onRetry,
            modifier = Modifier.align(Alignment.TopCenter),
        )
    } else {
        uiState.errorMessage?.let {
            TransientErrorBanner(
                it,
                viewModel::clearError,
                modifier = Modifier.align(Alignment.TopCenter),
            )
        }
    }
}

@Composable
private fun SelectedEventPane(
    uiState: BulletFeedUiState,
    selectedEventId: String,
    selectedFeedItemId: String?,
    onClearEvent: () -> Unit,
    viewModel: BulletFeedViewModel,
) {
    val detail = uiState.eventDetail.takeIf { uiState.eventDetailId == selectedEventId }
    val feedContext = uiState.events.firstOrNull { it.id == selectedEventId }
    when {
        detail != null -> EventDetailScreen(
            event = detail,
            feedContext = feedContext,
            onBack = onClearEvent,
            onFeedback = { feedback -> viewModel.updateEventFeedback(selectedEventId, feedback) },
            onFollow = { viewModel.toggleFollowing(selectedEventId) },
            onMarkCurrentStateKnown = { catchUp ->
                viewModel.markEventCurrentStateKnown(selectedEventId, catchUp)
            },
            isSavingKnowledgeBootstrap = uiState.isSavingKnowledgeBootstrap,
        )
        uiState.isEventDetailLoading -> DetailLoadingScreen("Eventを読み込み中", onClearEvent)
        else -> DetailErrorScreen(
            message = uiState.eventDetailError ?: "Eventを表示できません。",
            onBack = onClearEvent,
            onRetry = { viewModel.loadEventDetail(selectedEventId, selectedFeedItemId) },
        )
    }
}

@Composable
private fun SelectedVulnerabilityPane(
    uiState: BulletFeedUiState,
    selectedVulnerabilityId: String,
    onClearVulnerability: () -> Unit,
    viewModel: BulletFeedViewModel,
) {
    val alert = uiState.vulnerabilityDetail.takeIf { uiState.vulnerabilityDetailId == selectedVulnerabilityId }
    when {
        alert != null -> VulnerabilityDetailScreen(
            alert = alert,
            onBack = onClearVulnerability,
            onStatusChange = { viewModel.updateVulnerabilityStatus(selectedVulnerabilityId, it) },
        )
        uiState.isVulnerabilityDetailLoading -> DetailLoadingScreen("Alertを読み込み中", onClearVulnerability)
        else -> DetailErrorScreen(
            message = uiState.vulnerabilityDetailError ?: "Alertを表示できません。",
            onBack = onClearVulnerability,
            onRetry = { viewModel.loadVulnerabilityDetail(selectedVulnerabilityId) },
        )
    }
}

@Composable
internal fun OfflineRecoveryBanner(
    hasStaleFeed: Boolean,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) = Card(
    modifier = modifier
        .padding(12.dp)
        .fillMaxWidth()
        .testTag("offline-recovery-banner"),
    colors = CardDefaults.cardColors(containerColor = Color(0xFFFFE3B3)),
    shape = RoundedCornerShape(16.dp),
) {
    Column(Modifier.padding(14.dp)) {
        Text(
            "オフラインです",
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
            fontWeight = FontWeight.Bold,
            color = Color(0xFF5C3B00),
        )
        Text(
            if (hasStaleFeed) {
                "最後に読み込めたフィードを表示しています。再接続後に再試行してください。"
            } else {
                "フィードを読み込めませんでした。接続を確認して再試行してください。"
            },
            modifier = Modifier.padding(top = 4.dp),
            color = Color(0xFF5C3B00),
            style = MaterialTheme.typography.bodySmall,
        )
        Spacer(Modifier.height(8.dp))
        AccessiblePrimaryButton(
            onClick = onRetry,
            modifier = Modifier.fillMaxWidth().testTag("offline-recovery-retry"),
        ) {
            Text("再試行")
        }
    }
}

@Composable
private fun MainNavigation(
    uiState: BulletFeedUiState,
    tab: AppTab,
    onTabChange: (AppTab) -> Unit,
    onFilterChange: (FeedFilter) -> Unit,
    onEventSelect: (FeedEvent) -> Unit,
    onVulnerabilitySelect: (VulnerabilityAlert) -> Unit,
    onNotificationsOpen: () -> Unit,
    onGithubSetupOpen: () -> Unit,
    onEventFeedback: (String, Feedback) -> Unit,
    onFollow: (String) -> Unit,
    onAddTopic: (String, TopicType) -> Unit,
    onRemoveTopic: (String) -> Unit,
    onSearchTopics: (String) -> Unit,
    onAddTopicSearchResult: (UserTopic) -> Unit,
    onPriorityChange: (String, TopicPriority) -> Unit,
    onReorderTopics: (List<String>) -> Unit,
    onAddRecommendedTopic: (TopicRecommendation) -> Unit,
    onIgnoreTopicRecommendation: (String) -> Unit,
    onSaveProfile: (UserProfile) -> Unit,
    onDeleteAccount: () -> Unit,
    onApproveRecommendation: (String) -> Unit,
    onIgnoreRecommendation: (String) -> Unit,
    onAddSubscription: (UserSourceKind, String, String) -> Unit,
    onRemoveSubscription: (String) -> Unit,
    onDiscoverSiteFeeds: (String) -> Unit,
    onResetKnowledgeBootstrap: () -> Unit,
    onResetLearnedRanking: () -> Unit,
    onLoadMoreFeed: () -> Unit,
    onVisibleFeedItems: (List<ViewportItemSnapshot>) -> Unit,
) {
    val pane: @Composable (PaddingValues) -> Unit = { innerPadding ->
        AppTabPane(
            uiState = uiState,
            tab = tab,
            innerPadding = innerPadding,
            onTabChange = onTabChange,
            onFilterChange = onFilterChange,
            onEventSelect = onEventSelect,
            onVulnerabilitySelect = onVulnerabilitySelect,
            onNotificationsOpen = onNotificationsOpen,
            onGithubSetupOpen = onGithubSetupOpen,
            onEventFeedback = onEventFeedback,
            onFollow = onFollow,
            onAddTopic = onAddTopic,
            onRemoveTopic = onRemoveTopic,
            onSearchTopics = onSearchTopics,
            onAddTopicSearchResult = onAddTopicSearchResult,
            onPriorityChange = onPriorityChange,
            onReorderTopics = onReorderTopics,
            onAddRecommendedTopic = onAddRecommendedTopic,
            onIgnoreTopicRecommendation = onIgnoreTopicRecommendation,
            onSaveProfile = onSaveProfile,
            onDeleteAccount = onDeleteAccount,
            onApproveRecommendation = onApproveRecommendation,
            onIgnoreRecommendation = onIgnoreRecommendation,
            onAddSubscription = onAddSubscription,
            onRemoveSubscription = onRemoveSubscription,
            onDiscoverSiteFeeds = onDiscoverSiteFeeds,
            onResetKnowledgeBootstrap = onResetKnowledgeBootstrap,
            onResetLearnedRanking = onResetLearnedRanking,
            onLoadMoreFeed = onLoadMoreFeed,
            onVisibleFeedItems = onVisibleFeedItems,
        )
    }
    AppChromeShellForWindow(
        tab = tab,
        securityActionCount = uiState.securityActionCount,
        onTabChange = onTabChange,
        content = pane,
    )
}

@Composable
internal fun AppListDetailSplit(
    list: @Composable () -> Unit,
    detail: @Composable () -> Unit,
) {
    Row(Modifier.fillMaxSize().testTag("app-list-detail")) {
        Box(Modifier.weight(1f).fillMaxHeight().testTag("app-list-pane")) {
            list()
        }
        VerticalDivider()
        Box(Modifier.weight(1f).fillMaxHeight().testTag("app-detail-pane")) {
            detail()
        }
    }
}

@Composable
internal fun AppChromeShellForWindow(
    tab: AppTab,
    securityActionCount: Int,
    onTabChange: (AppTab) -> Unit,
    content: @Composable (PaddingValues) -> Unit,
) {
    AppChromeShell(
        chrome = AppChromeLayout.fromWidthDp(LocalConfiguration.current.screenWidthDp),
        tab = tab,
        securityActionCount = securityActionCount,
        onTabChange = onTabChange,
        content = content,
    )
}

private fun appChromeTabModifier(item: AppTab): Modifier =
    Modifier
        .testTag("app-chrome-tab-${item.name.lowercase()}")
        .defaultMinSize(
            minWidth = AppReadability.MIN_TOUCH_TARGET_DP.dp,
            minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp,
        )

@Composable
internal fun AppChromeShell(
    chrome: AppChromeLayout,
    tab: AppTab,
    securityActionCount: Int,
    onTabChange: (AppTab) -> Unit,
    content: @Composable (PaddingValues) -> Unit,
) {
    if (chrome == AppChromeLayout.NAVIGATION_RAIL) {
        Row(Modifier.fillMaxSize()) {
            NavigationRail(
                modifier = Modifier
                    .fillMaxHeight()
                    .testTag("app-chrome-navigation-rail"),
                containerColor = Color(0xFFF6EFEB),
            ) {
                AppTab.entries.forEach { item ->
                    NavigationRailItem(
                        selected = tab == item,
                        onClick = { onTabChange(item) },
                        icon = { AppTabNavIcon(item, securityActionCount) },
                        label = { Text(item.label) },
                        modifier = appChromeTabModifier(item),
                    )
                }
            }
            Scaffold(modifier = Modifier.weight(1f), content = content)
        }
    } else {
        Scaffold(
            bottomBar = {
                NavigationBar(
                    modifier = Modifier.testTag("app-chrome-bottom-bar"),
                    containerColor = Color(0xFFF6EFEB),
                ) {
                    AppTab.entries.forEach { item ->
                        NavigationBarItem(
                            selected = tab == item,
                            onClick = { onTabChange(item) },
                            icon = { AppTabNavIcon(item, securityActionCount) },
                            label = { Text(item.label) },
                            modifier = appChromeTabModifier(item),
                        )
                    }
                }
            },
            content = content,
        )
    }
}

@Composable
private fun AppTabNavIcon(
    item: AppTab,
    securityActionCount: Int,
) {
    val tabIcon = when (item) {
        AppTab.FEED -> Icons.Default.Home
        AppTab.SECURITY -> Icons.Default.Security
        AppTab.SEARCH -> Icons.Default.Search
        AppTab.TOPICS -> Icons.AutoMirrored.Filled.List
        AppTab.SETTINGS -> Icons.Default.Settings
    }
    if (item == AppTab.SECURITY && securityActionCount > 0) {
        BadgedBox(badge = { Badge { Text("$securityActionCount") } }) {
            Icon(tabIcon, contentDescription = item.label)
        }
    } else {
        Icon(tabIcon, contentDescription = item.label)
    }
}

@Composable
private fun AppTabPane(
    uiState: BulletFeedUiState,
    tab: AppTab,
    innerPadding: PaddingValues,
    onTabChange: (AppTab) -> Unit,
    onFilterChange: (FeedFilter) -> Unit,
    onEventSelect: (FeedEvent) -> Unit,
    onVulnerabilitySelect: (VulnerabilityAlert) -> Unit,
    onNotificationsOpen: () -> Unit,
    onGithubSetupOpen: () -> Unit,
    onEventFeedback: (String, Feedback) -> Unit,
    onFollow: (String) -> Unit,
    onAddTopic: (String, TopicType) -> Unit,
    onRemoveTopic: (String) -> Unit,
    onSearchTopics: (String) -> Unit,
    onAddTopicSearchResult: (UserTopic) -> Unit,
    onPriorityChange: (String, TopicPriority) -> Unit,
    onReorderTopics: (List<String>) -> Unit,
    onAddRecommendedTopic: (TopicRecommendation) -> Unit,
    onIgnoreTopicRecommendation: (String) -> Unit,
    onSaveProfile: (UserProfile) -> Unit,
    onDeleteAccount: () -> Unit,
    onApproveRecommendation: (String) -> Unit,
    onIgnoreRecommendation: (String) -> Unit,
    onAddSubscription: (UserSourceKind, String, String) -> Unit,
    onRemoveSubscription: (String) -> Unit,
    onDiscoverSiteFeeds: (String) -> Unit,
    onResetKnowledgeBootstrap: () -> Unit,
    onResetLearnedRanking: () -> Unit,
    onLoadMoreFeed: () -> Unit,
    onVisibleFeedItems: (List<ViewportItemSnapshot>) -> Unit,
) {
    when (tab) {
        AppTab.FEED -> FeedScreen(
            events = uiState.events,
            filter = uiState.feedFilter,
            onFilterChange = onFilterChange,
            onEventClick = onEventSelect,
            onFeedback = onEventFeedback,
            onFollow = onFollow,
            securityActionCount = uiState.securityActionCount,
            onSecurityClick = { onTabChange(AppTab.SECURITY) },
            unreadNotificationCount = uiState.unreadNotificationCount,
            onNotificationsClick = onNotificationsOpen,
            nextCursor = uiState.feedNextCursor,
            isLoadingMore = uiState.isFeedLoadingMore,
            isFiltering = uiState.isFeedFiltering,
            loadMoreError = uiState.feedLoadMoreError,
            onLoadMore = onLoadMoreFeed,
            onVisibleFeedItems = onVisibleFeedItems,
            onTopicsClick = { onTabChange(AppTab.TOPICS) },
            onGithubClick = onGithubSetupOpen,
            hasFollowedTopics = uiState.topicItems.isNotEmpty(),
            modifier = Modifier.padding(innerPadding),
        )
        AppTab.SECURITY -> SecurityDashboardScreen(
            alerts = uiState.vulnerabilityAlerts,
            onAlertClick = onVulnerabilitySelect,
            modifier = Modifier.padding(innerPadding),
        )
        AppTab.SEARCH -> SearchScreen(uiState.events, onEventSelect, Modifier.padding(innerPadding))
        AppTab.TOPICS -> TopicsScreen(
            topics = uiState.topicItems,
            searchResults = uiState.topicSearchResults,
            searchQuery = uiState.topicSearchQuery,
            isSearching = uiState.isTopicSearchLoading,
            githubConnected = uiState.githubConnected,
            topicSyncMessage = uiState.githubTopicSyncMessage,
            onGithubClick = onGithubSetupOpen,
            onSearchTopics = onSearchTopics,
            onAddTopic = onAddTopic,
            onAddSearchResult = onAddTopicSearchResult,
            onRemoveTopic = onRemoveTopic,
            onPriorityChange = onPriorityChange,
            onReorderTopics = onReorderTopics,
            recommendedTopics = uiState.topicRecommendations,
            onAddRecommendation = onAddRecommendedTopic,
            onIgnoreRecommendation = onIgnoreTopicRecommendation,
            modifier = Modifier.padding(innerPadding),
        )
        AppTab.SETTINGS -> SettingsScreen(
            profile = uiState.profile,
            isSaving = uiState.isSavingProfile,
            isDeletingAccount = uiState.isDeletingAccount,
            onSaveProfile = onSaveProfile,
            onDeleteAccount = onDeleteAccount,
            recommendations = uiState.sourceRecommendations,
            decidingRecommendationId = uiState.decidingRecommendationId,
            onApproveRecommendation = onApproveRecommendation,
            onIgnoreRecommendation = onIgnoreRecommendation,
            subscriptions = uiState.sourceSubscriptions,
            isSavingSubscription = uiState.isSavingSourceSubscription,
            subscriptionError = uiState.sourceSubscriptionError,
            onAddSubscription = onAddSubscription,
            onRemoveSubscription = onRemoveSubscription,
            siteFeedDiscoverResult = uiState.siteFeedDiscoverResult,
            isDiscoveringSiteFeeds = uiState.isDiscoveringSiteFeeds,
            siteFeedDiscoverError = uiState.siteFeedDiscoverError,
            onDiscoverSiteFeeds = onDiscoverSiteFeeds,
            knowledgeBootstrap = uiState.knowledgeBootstrap,
            isSavingKnowledgeBootstrap = uiState.isSavingKnowledgeBootstrap,
            onResetKnowledgeBootstrap = onResetKnowledgeBootstrap,
            onResetLearnedRanking = onResetLearnedRanking,
            modifier = Modifier.padding(innerPadding),
        )
    }
}

@Composable
internal fun AppLoadingScreen() =
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator(color = Color(0xFFA6231C))
        Text(
            "データを読み込み中…",
            modifier = Modifier.padding(top = 16.dp).semantics { liveRegion = LiveRegionMode.Polite },
            color = Color(0xFF655F69),
        )
    }

@Composable
internal fun ReauthenticationScreen(
    isAuthorizing: Boolean,
    onReauthenticate: () -> Unit,
) = Column(
    modifier = Modifier
        .fillMaxSize()
        .padding(32.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
    verticalArrangement = Arrangement.Center,
) {
    Text(
        "同じアカウントへ再認証",
        modifier = Modifier.semantics {
            heading()
            liveRegion = LiveRegionMode.Assertive
        },
        style = MaterialTheme.typography.titleLarge,
        fontWeight = FontWeight.Bold,
    )
    Text(
        "期限切れの保護データは画面から破棄しました。refresh tokenを回転し、利用できない場合はGitHub identityで既存のBulletFeed userを復旧します。新しい匿名userは作成しません。",
        modifier = Modifier.padding(top = 10.dp),
        color = Color(0xFF655F69),
    )
    Spacer(Modifier.height(18.dp))
    AccessiblePrimaryButton(
        onClick = onReauthenticate,
        enabled = !isAuthorizing,
        modifier = Modifier.testTag("session-reauth-button"),
    ) {
        if (isAuthorizing) CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp))
        Text(if (isAuthorizing) "GitHub認証を確認中" else "アカウントを復旧")
    }
}

@Composable
internal fun GithubAuthorizationRequiredScreen(
    isAuthorizing: Boolean,
    errorMessage: String?,
    onAuthorize: () -> Unit,
) = Column(
    modifier = Modifier
        .fillMaxSize()
        .padding(32.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
    verticalArrangement = Arrangement.Center,
) {
    Text(
        "GitHub連携を完了",
        modifier = Modifier.semantics {
            heading()
            liveRegion = if (errorMessage != null) LiveRegionMode.Assertive else LiveRegionMode.Polite
        },
        style = MaterialTheme.typography.headlineSmall,
        fontWeight = FontWeight.Bold,
    )
    Text(
        "GitHubを使うonboardingは、OAuth成功とrepository選択が完了するまでreadyになりません。",
        modifier = Modifier.padding(top = 10.dp),
        color = Color(0xFF655F69),
    )
    errorMessage?.let { Text(it, modifier = Modifier.padding(top = 12.dp), color = Color(0xFF8F1D18)) }
    Spacer(Modifier.height(18.dp))
    AccessiblePrimaryButton(
        onClick = onAuthorize,
        enabled = !isAuthorizing,
        modifier = Modifier.fillMaxWidth().testTag("github-oauth-required-authorize"),
    ) {
        Text(if (isAuthorizing) "認可完了を確認中" else "GitHubで認可する")
    }
}

@Composable
internal fun GithubReauthorizationRequiredScreen(
    accountLogin: String?,
    isAuthorizing: Boolean,
    showBack: Boolean,
    onBack: () -> Unit,
    onAuthorize: () -> Unit,
) = Column(
    modifier = Modifier
        .fillMaxSize()
        .padding(32.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
    verticalArrangement = Arrangement.Center,
) {
    Text(
        "GitHubの再認証が必要です",
        modifier = Modifier.semantics {
            heading()
            liveRegion = LiveRegionMode.Assertive
        },
        style = MaterialTheme.typography.headlineSmall,
        fontWeight = FontWeight.Bold,
    )
    Text(
        accountLogin?.let {
            "$it のGitHub credentialが失効したか、repository accessが失われました。BulletFeed userは維持したまま再認証します。"
        } ?: "GitHub credentialが失効したか、repository accessが失われました。BulletFeed userは維持したまま再認証します。",
        modifier = Modifier.padding(top = 10.dp),
        color = Color(0xFF655F69),
    )
    Spacer(Modifier.height(18.dp))
    AccessiblePrimaryButton(
        onClick = onAuthorize,
        enabled = !isAuthorizing,
        modifier = Modifier.fillMaxWidth().testTag("github-reauthorize-button"),
    ) {
        Text(if (isAuthorizing) "認可完了を確認中" else "GitHubを再認証")
    }
    if (showBack) {
        Spacer(Modifier.height(8.dp))
        AccessiblePrimaryButton(
            onClick = onBack,
            enabled = !isAuthorizing,
            modifier = Modifier.testTag("github-reauthorize-back"),
        ) {
            Text("戻る")
        }
    }
}

@Composable
internal fun AppErrorScreen(message: String, onRetry: () -> Unit) =
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            "読み込みに失敗しました",
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Assertive },
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
        )
        Text(message, modifier = Modifier.padding(top = 8.dp), color = Color(0xFF655F69))
        Spacer(Modifier.height(18.dp))
        AccessiblePrimaryButton(
            onClick = onRetry,
            modifier = Modifier.testTag("app-error-retry"),
        ) {
            Text("再試行")
        }
    }

@Composable
internal fun DetailLoadingScreen(title: String, onBack: () -> Unit) =
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator()
        Text(
            title,
            modifier = Modifier.padding(top = 12.dp).semantics { liveRegion = LiveRegionMode.Polite },
        )
        Spacer(Modifier.height(18.dp))
        AccessiblePrimaryButton(
            onClick = onBack,
            modifier = Modifier.testTag("detail-loading-back"),
        ) {
            Text("戻る")
        }
    }

@Composable
internal fun DetailErrorScreen(
    message: String,
    onBack: () -> Unit,
    onRetry: () -> Unit,
) = Column(
    modifier = Modifier
        .fillMaxSize()
        .padding(32.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
    verticalArrangement = Arrangement.Center,
) {
    Text(
        "詳細を表示できません",
        modifier = Modifier.semantics {
            heading()
            liveRegion = LiveRegionMode.Assertive
        },
        style = MaterialTheme.typography.titleLarge,
        fontWeight = FontWeight.Bold,
    )
    Text(message, modifier = Modifier.padding(top = 8.dp), color = Color(0xFF655F69))
    Spacer(Modifier.height(18.dp))
    AccessiblePrimaryButton(
        onClick = onRetry,
        modifier = Modifier.testTag("detail-error-retry"),
    ) {
        Text("再試行")
    }
    Spacer(Modifier.height(8.dp))
    AccessiblePrimaryButton(
        onClick = onBack,
        modifier = Modifier.testTag("detail-error-back"),
    ) {
        Text("戻る")
    }
}

@Composable
internal fun KnowledgeBootstrapPromptDialog(
    prompt: KnowledgeBootstrapPrompt,
    isSaving: Boolean,
    onAlreadyKnew: () -> Unit,
    onCatchUp: () -> Unit,
    onDismiss: () -> Unit,
) {
    val kindLabel =
        when (prompt.subjectKind) {
            BootstrapSubjectKind.EVENT -> "この Event"
            BootstrapSubjectKind.TOPIC -> "この Topic"
            BootstrapSubjectKind.GLOBAL -> "全体"
        }
    AlertDialog(
        onDismissRequest = { if (!isSaving) onDismiss() },
        title = { Text("すでに知っていますか") },
        text = {
            Column {
                Text("$kindLabel「${prompt.title}」をフォローしました。")
                if (prompt.currentStateSummary.isNotBlank()) {
                    Text(
                        "現在状態: ${prompt.currentStateSummary}",
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
                Text(
                    "「すでに知っている」は、いま真である現在状態だけを既知にします。途中経過は既知にしません。",
                    modifier = Modifier.padding(top = 8.dp),
                )
                Text(
                    "「これから追う（catch up）」は開始時刻だけを残し、過去は既知にしません。",
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
        },
        confirmButton = {
            AccessiblePrimaryButton(onClick = onAlreadyKnew, enabled = !isSaving) {
                Text("この現在状態は知っている")
            }
        },
        dismissButton = {
            Column {
                AccessibleOutlinedButton(onClick = onCatchUp, enabled = !isSaving) {
                    Text("これから追う")
                }
                AccessibleTextButton(onClick = onDismiss, enabled = !isSaving) {
                    Text("あとで")
                }
            }
        },
    )
}

@Composable
internal fun TransientErrorBanner(
    message: String,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) = Card(
    modifier = modifier
        .statusBarsPadding()
        .padding(12.dp)
        .fillMaxWidth()
        .testTag("transient-error-banner"),
    colors = CardDefaults.cardColors(containerColor = Color(0xFF8F1D18)),
) {
    RowWithDismiss(message, onDismiss)
}

@Composable
private fun RowWithDismiss(message: String, onDismiss: () -> Unit) {
    androidx.compose.foundation.layout.Row(
        modifier = Modifier.padding(start = 14.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            message,
            modifier = Modifier.weight(1f).semantics { liveRegion = LiveRegionMode.Assertive },
            color = Color.White,
            style = MaterialTheme.typography.bodySmall,
        )
        AccessibleIconButton(onClick = onDismiss) {
            Icon(Icons.Default.Close, contentDescription = "閉じる", tint = Color.White)
        }
    }
}

private fun bulletFeedColorScheme() = lightColorScheme(
    primary = Color(0xFFA6231C),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFFCE8E6),
    onPrimaryContainer = Color(0xFF6F100C),
    secondary = Color(0xFF006A67),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFD7F1EE),
    onSecondaryContainer = Color(0xFF003D3B),
    tertiary = Color(0xFF8A5A00),
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFFFE3B3),
    onTertiaryContainer = Color(0xFF3D2800),
    surface = Color(0xFFFFFBF8),
    onSurface = Color(0xFF211A18),
    surfaceVariant = Color(0xFFF6EFEB),
    onSurfaceVariant = Color(0xFF554542),
    background = Color(0xFFFFFBF8),
    onBackground = Color(0xFF211A18),
    outline = Color(0xFF88736E),
    outlineVariant = Color(0xFFDCC2BC),
)
