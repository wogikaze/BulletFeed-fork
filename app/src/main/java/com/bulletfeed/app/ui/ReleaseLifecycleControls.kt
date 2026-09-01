package com.bulletfeed.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp

/**
 * Release wrapper around the feed screen. The underlying list remains responsible for viewport
 * exposure reporting; this only adds an explicit refresh path in addition to resume/foreground refresh.
 */
@Composable
fun FeedScreen(
    events: List<FeedEvent>,
    filter: FeedFilter,
    onFilterChange: (FeedFilter) -> Unit,
    onEventClick: (FeedEvent) -> Unit,
    onFeedback: (String, Feedback) -> Unit,
    onFollow: (String) -> Unit,
    securityActionCount: Int,
    onSecurityClick: () -> Unit,
    unreadNotificationCount: Int,
    onNotificationsClick: () -> Unit,
    nextCursor: String?,
    isLoadingMore: Boolean,
    isFiltering: Boolean,
    loadMoreError: String?,
    onRefresh: () -> Unit,
    onLoadMore: () -> Unit,
    onVisibleFeedItems: (List<ViewportItemSnapshot>) -> Unit,
    onTopicsClick: () -> Unit,
    onGithubClick: () -> Unit,
    hasFollowedTopics: Boolean = false,
    modifier: Modifier = Modifier,
) = Box(modifier = modifier.fillMaxSize()) {
    FeedScreen(
        events = events,
        filter = filter,
        onFilterChange = onFilterChange,
        onEventClick = onEventClick,
        onFeedback = onFeedback,
        onFollow = onFollow,
        securityActionCount = securityActionCount,
        onSecurityClick = onSecurityClick,
        unreadNotificationCount = unreadNotificationCount,
        onNotificationsClick = onNotificationsClick,
        nextCursor = nextCursor,
        isLoadingMore = isLoadingMore,
        isFiltering = isFiltering,
        loadMoreError = loadMoreError,
        onLoadMore = onLoadMore,
        onVisibleFeedItems = onVisibleFeedItems,
        onTopicsClick = onTopicsClick,
        onGithubClick = onGithubClick,
        hasFollowedTopics = hasFollowedTopics,
        modifier = Modifier.fillMaxSize(),
    )
    Box(Modifier.align(Alignment.TopEnd).padding(top = 68.dp, end = 20.dp)) {
        AccessibleOutlinedButton(
            onClick = onRefresh,
            enabled = !isFiltering,
            modifier = Modifier.testTag("feed-refresh-button"),
        ) {
            Text("更新")
        }
    }
}

/** Account deletion is intentionally destructive and requires an explicit confirmation. */
@Composable
fun SettingsScreen(
    profile: UserProfile,
    isSaving: Boolean,
    isDeletingAccount: Boolean,
    onSaveProfile: (UserProfile) -> Unit,
    onDeleteAccount: () -> Unit,
    recommendations: List<SourceRecommendation> = emptyList(),
    decidingRecommendationId: String? = null,
    onApproveRecommendation: (String) -> Unit = {},
    onIgnoreRecommendation: (String) -> Unit = {},
    subscriptions: List<SourceSubscription> = emptyList(),
    isSavingSubscription: Boolean = false,
    subscriptionError: String? = null,
    onAddSubscription: (UserSourceKind, String, String) -> Unit = { _, _, _ -> },
    onRemoveSubscription: (String) -> Unit = {},
    siteFeedDiscoverResult: SiteFeedDiscoverResult? = null,
    isDiscoveringSiteFeeds: Boolean = false,
    siteFeedDiscoverError: String? = null,
    onDiscoverSiteFeeds: (String) -> Unit = {},
    knowledgeBootstrap: KnowledgeBootstrapSummary = KnowledgeBootstrapSummary(
        version = "",
        explicitKnownFactCount = 0,
        inferredFactCount = 0,
    ),
    isSavingKnowledgeBootstrap: Boolean = false,
    onResetKnowledgeBootstrap: () -> Unit = {},
    onResetLearnedRanking: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    var confirmDelete by rememberSaveable { mutableStateOf(false) }
    Column(modifier.fillMaxSize()) {
        SettingsScreen(
            profile = profile,
            isSaving = isSaving,
            onSaveProfile = onSaveProfile,
            recommendations = recommendations,
            decidingRecommendationId = decidingRecommendationId,
            onApproveRecommendation = onApproveRecommendation,
            onIgnoreRecommendation = onIgnoreRecommendation,
            subscriptions = subscriptions,
            isSavingSubscription = isSavingSubscription,
            subscriptionError = subscriptionError,
            onAddSubscription = onAddSubscription,
            onRemoveSubscription = onRemoveSubscription,
            siteFeedDiscoverResult = siteFeedDiscoverResult,
            isDiscoveringSiteFeeds = isDiscoveringSiteFeeds,
            siteFeedDiscoverError = siteFeedDiscoverError,
            onDiscoverSiteFeeds = onDiscoverSiteFeeds,
            knowledgeBootstrap = knowledgeBootstrap,
            isSavingKnowledgeBootstrap = isSavingKnowledgeBootstrap,
            onResetKnowledgeBootstrap = onResetKnowledgeBootstrap,
            onResetLearnedRanking = onResetLearnedRanking,
            modifier = Modifier.weight(1f),
        )
        Spacer(Modifier.height(12.dp))
        AccessibleOutlinedButton(
            onClick = { confirmDelete = true },
            enabled = !isDeletingAccount,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .testTag("settings-delete-account"),
        ) {
            if (isDeletingAccount) {
                CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp))
            }
            Text(if (isDeletingAccount) "アカウントを削除中" else "アカウントと保存データを削除")
        }
    }

    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { if (!isDeletingAccount) confirmDelete = false },
            title = { Text("アカウントを削除しますか？") },
            text = {
                Text("プロフィール、テーマ、feedback、knownness、GitHub連携、通知など、このBulletFeed userに紐づく保存データを削除します。")
            },
            confirmButton = {
                AccessiblePrimaryButton(
                    onClick = {
                        confirmDelete = false
                        onDeleteAccount()
                    },
                    enabled = !isDeletingAccount,
                    modifier = Modifier.testTag("settings-delete-confirm"),
                ) { Text("削除する") }
            },
            dismissButton = {
                AccessibleTextButton(
                    onClick = { confirmDelete = false },
                    enabled = !isDeletingAccount,
                    modifier = Modifier.testTag("settings-delete-cancel"),
                ) {
                    Text("キャンセル")
                }
            },
        )
    }
}
