package com.bulletfeed.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/**
 * Release wrapper around the feed screen. The underlying list remains responsible for viewport
 * exposure reporting; this adds pull-to-refresh in addition to resume/foreground refresh.
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
    isRefreshing: Boolean = false,
    onLoadMore: () -> Unit,
    onVisibleFeedItems: (List<ViewportItemSnapshot>) -> Unit,
    onTopicsClick: () -> Unit,
    onGithubClick: () -> Unit,
    hasFollowedTopics: Boolean = false,
    modifier: Modifier = Modifier,
) = Box(modifier = modifier.fillMaxSize()) {
    PullToRefreshBox(
        isRefreshing = isRefreshing,
        onRefresh = onRefresh,
        state = rememberPullToRefreshState(),
        modifier = Modifier.fillMaxSize(),
    ) {
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
    }
}
