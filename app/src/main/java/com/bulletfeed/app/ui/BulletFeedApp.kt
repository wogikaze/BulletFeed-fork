package com.bulletfeed.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel

@Composable
fun BulletFeedApp(viewModel: BulletFeedViewModel = viewModel(factory = BulletFeedViewModel.Factory)) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var tab by remember { mutableStateOf(AppTab.FEED) }
    var filter by remember { mutableStateOf(FeedFilter.ALL) }
    var selectedEventId by remember { mutableStateOf<String?>(null) }
    var selectedVulnerabilityId by remember { mutableStateOf<String?>(null) }
    var notificationsOpen by remember { mutableStateOf(false) }
    var githubSetupOpen by remember { mutableStateOf(false) }

    MaterialTheme(colorScheme = bulletFeedColorScheme()) {
        Surface(modifier = Modifier.fillMaxSize()) {
            when {
                uiState.isLoading && uiState.events.isEmpty() -> AppLoadingScreen()
                uiState.errorMessage != null && uiState.events.isEmpty() ->
                    AppErrorScreen(
                        message = uiState.errorMessage.orEmpty(),
                        onRetry = viewModel::refresh,
                    )
                !uiState.onboardingCompleted ->
                    Box(Modifier.fillMaxSize()) {
                        OnboardingScreen(
                            initialProfile = uiState.profile,
                            initialTopics = uiState.topics,
                            isSaving = uiState.isSavingOnboarding,
                            onComplete = viewModel::completeOnboarding,
                        )
                        uiState.errorMessage?.let { message ->
                            TransientErrorBanner(message = message, onDismiss = viewModel::clearError)
                        }
                    }
                else ->
                    Box(Modifier.fillMaxSize()) {
                        BulletFeedContent(
                            uiState = uiState,
                            tab = tab,
                            filter = filter,
                            selectedEventId = selectedEventId,
                            selectedVulnerabilityId = selectedVulnerabilityId,
                            notificationsOpen = notificationsOpen,
                            githubSetupOpen = githubSetupOpen,
                            onTabChange = { tab = it },
                            onFilterChange = { filter = it },
                            onEventSelect = { selectedEventId = it },
                            onVulnerabilitySelect = { selectedVulnerabilityId = it },
                            onNotificationsOpenChange = { notificationsOpen = it },
                            onGithubSetupOpenChange = { githubSetupOpen = it },
                            onEventFeedback = viewModel::updateEventFeedback,
                            onFollow = viewModel::toggleFollowing,
                            onVulnerabilityStatusChange = viewModel::updateVulnerabilityStatus,
                            onNotificationRead = viewModel::markNotificationRead,
                            onAllNotificationsRead = viewModel::markAllNotificationsRead,
                            onGithubConnect = viewModel::connectGithub,
                            onAddTopic = viewModel::addTopic,
                            onRemoveTopic = viewModel::removeTopic,
                        )
                        uiState.errorMessage?.let { message ->
                            TransientErrorBanner(message = message, onDismiss = viewModel::clearError)
                        }
                    }
            }
        }
    }
}

@Composable
private fun BulletFeedContent(
    uiState: BulletFeedUiState,
    tab: AppTab,
    filter: FeedFilter,
    selectedEventId: String?,
    selectedVulnerabilityId: String?,
    notificationsOpen: Boolean,
    githubSetupOpen: Boolean,
    onTabChange: (AppTab) -> Unit,
    onFilterChange: (FeedFilter) -> Unit,
    onEventSelect: (String?) -> Unit,
    onVulnerabilitySelect: (String?) -> Unit,
    onNotificationsOpenChange: (Boolean) -> Unit,
    onGithubSetupOpenChange: (Boolean) -> Unit,
    onEventFeedback: (String, Feedback) -> Unit,
    onFollow: (String) -> Unit,
    onVulnerabilityStatusChange: (String, VulnerabilityStatus) -> Unit,
    onNotificationRead: (String) -> Unit,
    onAllNotificationsRead: () -> Unit,
    onGithubConnect: () -> Unit,
    onAddTopic: (String) -> Unit,
    onRemoveTopic: (String) -> Unit,
) {
    val event = selectedEventId?.let { id -> uiState.events.firstOrNull { it.id == id } }
    val vulnerability = selectedVulnerabilityId?.let { id -> uiState.vulnerabilityAlerts.firstOrNull { it.id == id } }

    when {
        event != null ->
            EventDetailScreen(
                event = event,
                onBack = { onEventSelect(null) },
                onFeedback = { feedback -> onEventFeedback(event.id, feedback) },
                onFollow = { onFollow(event.id) },
            )
        vulnerability != null ->
            VulnerabilityDetailScreen(
                alert = vulnerability,
                onBack = { onVulnerabilitySelect(null) },
                onStatusChange = { status -> onVulnerabilityStatusChange(vulnerability.id, status) },
            )
        notificationsOpen ->
            NotificationsScreen(
                notifications = uiState.notifications,
                onBack = { onNotificationsOpenChange(false) },
                onNotificationClick = { notification ->
                    onNotificationRead(notification.id)
                    when (notification.targetType) {
                        NotificationTargetType.EVENT -> onEventSelect(notification.targetId)
                        NotificationTargetType.VULNERABILITY -> onVulnerabilitySelect(notification.targetId)
                    }
                },
                onMarkAllRead = onAllNotificationsRead,
            )
        githubSetupOpen ->
            GithubConnectionScreen(
                connected = uiState.githubConnected,
                onBack = { onGithubSetupOpenChange(false) },
                onConnect = onGithubConnect,
            )
        else ->
            MainNavigation(
                uiState = uiState,
                tab = tab,
                filter = filter,
                onTabChange = onTabChange,
                onFilterChange = onFilterChange,
                onEventSelect = { selected -> onEventSelect(selected.id) },
                onVulnerabilitySelect = { selected -> onVulnerabilitySelect(selected.id) },
                onNotificationsOpen = { onNotificationsOpenChange(true) },
                onGithubSetupOpen = { onGithubSetupOpenChange(true) },
                onEventFeedback = onEventFeedback,
                onFollow = onFollow,
                onAddTopic = onAddTopic,
                onRemoveTopic = onRemoveTopic,
            )
    }
}

@Composable
private fun MainNavigation(
    uiState: BulletFeedUiState,
    tab: AppTab,
    filter: FeedFilter,
    onTabChange: (AppTab) -> Unit,
    onFilterChange: (FeedFilter) -> Unit,
    onEventSelect: (FeedEvent) -> Unit,
    onVulnerabilitySelect: (VulnerabilityAlert) -> Unit,
    onNotificationsOpen: () -> Unit,
    onGithubSetupOpen: () -> Unit,
    onEventFeedback: (String, Feedback) -> Unit,
    onFollow: (String) -> Unit,
    onAddTopic: (String) -> Unit,
    onRemoveTopic: (String) -> Unit,
) = Scaffold(
    bottomBar = {
        NavigationBar(containerColor = Color(0xFFF6EFEB)) {
            AppTab.entries.forEach { item ->
                NavigationBarItem(
                    selected = tab == item,
                    onClick = { onTabChange(item) },
                    icon = {
                        val icon =
                            when (item) {
                                AppTab.FEED -> Icons.Default.Home
                                AppTab.SECURITY -> Icons.Default.Security
                                AppTab.SEARCH -> Icons.Default.Search
                                AppTab.TOPICS -> Icons.AutoMirrored.Filled.List
                                AppTab.SETTINGS -> Icons.Default.Settings
                            }
                        if (item == AppTab.SECURITY && uiState.securityActionCount > 0) {
                            BadgedBox(badge = { Badge { Text("${uiState.securityActionCount}") } }) {
                                Icon(icon, contentDescription = item.label)
                            }
                        } else {
                            Icon(icon, contentDescription = item.label)
                        }
                    },
                    label = { Text(item.label) },
                )
            }
        }
    },
) { innerPadding ->
    when (tab) {
        AppTab.FEED ->
            FeedScreen(
                events = uiState.events,
                filter = filter,
                onFilterChange = onFilterChange,
                onEventClick = { event ->
                    onEventFeedback(event.id, Feedback.READ)
                    onEventSelect(event)
                },
                onFeedback = onEventFeedback,
                onFollow = onFollow,
                securityActionCount = uiState.securityActionCount,
                onSecurityClick = { onTabChange(AppTab.SECURITY) },
                unreadNotificationCount = uiState.unreadNotificationCount,
                onNotificationsClick = onNotificationsOpen,
                modifier = Modifier.padding(innerPadding),
            )
        AppTab.SECURITY ->
            SecurityDashboardScreen(
                alerts = uiState.vulnerabilityAlerts,
                onAlertClick = onVulnerabilitySelect,
                modifier = Modifier.padding(innerPadding),
            )
        AppTab.SEARCH -> SearchScreen(uiState.events, onEventSelect, Modifier.padding(innerPadding))
        AppTab.TOPICS ->
            TopicsScreen(
                topics = uiState.topics,
                githubConnected = uiState.githubConnected,
                onGithubClick = onGithubSetupOpen,
                onAddTopic = onAddTopic,
                onRemoveTopic = onRemoveTopic,
                modifier = Modifier.padding(innerPadding),
            )
        AppTab.SETTINGS -> SettingsScreen(profile = uiState.profile, modifier = Modifier.padding(innerPadding))
    }
}

@Composable
private fun AppLoadingScreen() =
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator(color = Color(0xFFA6231C))
        Text("あなたに関係する変化を整理中…", modifier = Modifier.padding(top = 16.dp), color = Color(0xFF655F69))
    }

@Composable
private fun AppErrorScreen(
    message: String,
    onRetry: () -> Unit,
) = Column(
    modifier = Modifier.fillMaxSize().padding(32.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
    verticalArrangement = Arrangement.Center,
) {
    Text("読み込みに失敗しました", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    Text(message, modifier = Modifier.padding(top = 8.dp), color = Color(0xFF655F69))
    Button(onClick = onRetry, modifier = Modifier.padding(top = 18.dp)) { Text("再試行") }
}

@Composable
private fun TransientErrorBanner(
    message: String,
    onDismiss: () -> Unit,
) = Card(
    modifier = Modifier.statusBarsPadding().padding(12.dp).fillMaxWidth(),
    colors = CardDefaults.cardColors(containerColor = Color(0xFF8F1D18)),
) {
    androidx.compose.foundation.layout.Row(
        modifier = Modifier.padding(start = 14.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(message, modifier = Modifier.weight(1f), color = Color.White, style = MaterialTheme.typography.bodySmall)
        IconButton(onClick = onDismiss) {
            Icon(Icons.Default.Close, contentDescription = "閉じる", tint = Color.White)
        }
    }
}

private fun bulletFeedColorScheme() =
    lightColorScheme(
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

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun BulletFeedPreview() = BulletFeedApp()
