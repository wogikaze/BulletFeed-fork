package com.bulletfeed.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
        modifier = Modifier.fillMaxSize(),
    )
    OutlinedButton(
        onClick = onRefresh,
        enabled = !isFiltering,
        modifier = Modifier.align(Alignment.TopEnd).padding(top = 68.dp, end = 20.dp),
    ) {
        Text("更新")
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
    modifier: Modifier = Modifier,
) {
    var confirmDelete by rememberSaveable { mutableStateOf(false) }
    Column(modifier.fillMaxSize()) {
        SettingsScreen(
            profile = profile,
            isSaving = isSaving,
            onSaveProfile = onSaveProfile,
            modifier = Modifier.weight(1f),
        )
        OutlinedButton(
            onClick = { confirmDelete = true },
            enabled = !isDeletingAccount,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp),
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
                Button(
                    onClick = {
                        confirmDelete = false
                        onDeleteAccount()
                    },
                    enabled = !isDeletingAccount,
                ) { Text("削除する") }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = false }, enabled = !isDeletingAccount) {
                    Text("キャンセル")
                }
            },
        )
    }
}
