package com.bulletfeed.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Security
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.flow.distinctUntilChanged

@OptIn(ExperimentalMaterial3Api::class)
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
    onLoadMore: () -> Unit,
    onVisibleFeedItems: (List<ViewportItemSnapshot>) -> Unit,
    onTopicsClick: () -> Unit,
    onGithubClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    val urgentEvents = events.filter { event ->
        !event.read && (event.importance == Importance.CRITICAL || event.importance == Importance.HIGH)
    }
    val directUnreadCount = events.count { event -> !event.read && event.relation == Relation.DIRECT }

    LaunchedEffect(listState) {
        snapshotFlow {
            val layoutInfo = listState.layoutInfo
            val viewportStart = layoutInfo.viewportStartOffset
            val viewportEnd = layoutInfo.viewportEndOffset
            layoutInfo.visibleItemsInfo.mapNotNull { info ->
                val feedItemId = info.key as? String ?: return@mapNotNull null
                ViewportItemSnapshot(
                    feedItemId = feedItemId,
                    visibleRatio = visibleRatio(
                        offset = info.offset,
                        size = info.size,
                        viewportStart = viewportStart,
                        viewportEnd = viewportEnd,
                    ),
                )
            }
        }.distinctUntilChanged().collect { snapshots ->
            onVisibleFeedItems(snapshots)
        }
    }

    LazyColumn(state = listState, modifier = modifier.fillMaxSize()) {
        item {
            TopAppBar(
                title = { AppBarTitle("BulletFeed") },
                actions = {
                    AccessibleIconButton(onClick = onNotificationsClick) {
                        if (unreadNotificationCount > 0) {
                            BadgedBox(badge = { Badge { Text(unreadNotificationCount.coerceAtMost(99).toString()) } }) {
                                Icon(Icons.Default.Notifications, contentDescription = "通知を開く")
                            }
                        } else {
                            Icon(Icons.Default.Notifications, contentDescription = "通知を開く")
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFFFFFBF8)),
            )
            TodaySummary(urgentEvents, directUnreadCount, onEventClick)
            if (securityActionCount > 0) SecurityShortcut(securityActionCount, onSecurityClick)
            FilterRow(filter, events.size, onFilterChange)
            if (isFiltering) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Text("フィードを更新中", modifier = Modifier.padding(start = 8.dp), style = MaterialTheme.typography.bodySmall)
                }
            }
            FeedHeading(filter, events.size)
        }
        if (events.isEmpty() && !isFiltering) {
            item { EmptyFeed(filter, onFilterChange, onTopicsClick, onGithubClick) }
        } else {
            items(events, key = { it.feedItemId }) { event ->
                EventCard(event, onEventClick, onFeedback, onFollow)
            }
        }
        if (loadMoreError != null) {
            item { FeedLoadMoreError(loadMoreError) }
        }
        if (nextCursor != null) {
            item {
                AccessiblePrimaryButton(
                    onClick = onLoadMore,
                    enabled = !isLoadingMore && !isFiltering,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp),
                ) {
                    if (isLoadingMore) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(if (isLoadingMore) "読み込み中" else "次のページを読み込む")
                }
            }
        }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@Composable
private fun SecurityShortcut(actionCount: Int, onClick: () -> Unit) =
    Card(
        modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp).fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFCE8E6)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(38.dp).clip(CircleShape).background(Color(0xFFB42318)), contentAlignment = Alignment.Center) {
                Icon(Icons.Default.Security, contentDescription = null, tint = Color.White, modifier = Modifier.size(22.dp))
            }
            Column(Modifier.padding(start = 11.dp).weight(1f)) {
                Text("脆弱性への対応が $actionCount 件必要です", fontWeight = FontWeight.Bold, color = Color(0xFF8F1D18))
                Text("影響するrepositoryと修正版を確認", color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = "セキュリティを開く", tint = Color(0xFFB42318))
        }
    }

@Composable
private fun TodaySummary(
    urgentEvents: List<FeedEvent>,
    directUnreadCount: Int,
    onEventClick: (FeedEvent) -> Unit,
) = Card(
    modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp).fillMaxWidth(),
    colors = CardDefaults.cardColors(containerColor = Color(0xFF9D231C)),
    shape = RoundedCornerShape(24.dp),
) {
    Column(Modifier.padding(18.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(36.dp).clip(CircleShape).background(Color(0xFFC83C32)), contentAlignment = Alignment.Center) {
                Text("!", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp)
            }
            Spacer(Modifier.width(11.dp))
            Column(Modifier.weight(1f)) {
                Text("今日の優先順位", color = Color.White, fontWeight = FontWeight.Bold)
                Text("直接影響の未読が $directUnreadCount 件", color = Color(0xFFFFDAD5), style = MaterialTheme.typography.bodySmall)
            }
            Text("${urgentEvents.size}件", color = Color.White, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        }
        urgentEvents.firstOrNull()?.let { event ->
            Spacer(Modifier.height(14.dp))
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color.White.copy(alpha = 0.12f)).clickable {
                    onEventClick(event)
                }.padding(13.dp),
            ) {
                Text("${event.importance.label} · ${event.relation.label}", color = Color(0xFFFFD8A8), style = MaterialTheme.typography.labelMedium)
                ReadableTitle(
                    event.title,
                    color = Color.White,
                )
            }
        }
    }
}

@Composable
private fun FilterRow(selected: FeedFilter, currentCount: Int, onSelect: (FeedFilter) -> Unit) =
    LazyRow(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(FeedFilter.entries) { item ->
            AccessibleFilterChip(
                selected = selected == item,
                onClick = { onSelect(item) },
                label = if (selected == item) "${item.label} $currentCount" else item.label,
            )
        }
    }

@Composable
private fun FeedHeading(filter: FeedFilter, count: Int) =
    Row(
        modifier = Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("${filter.label}の変化", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Spacer(Modifier.weight(1f))
        Text("${count}件", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
    }

@Composable
internal fun EmptyFeed(
    filter: FeedFilter,
    onFilterChange: (FeedFilter) -> Unit,
    onTopicsClick: () -> Unit,
    onGithubClick: () -> Unit,
) = Column(
    Modifier
        .fillMaxWidth()
        .padding(30.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
) {
    Text(
        "表示する変化はありません",
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.Bold,
    )
    Spacer(Modifier.height(6.dp))
    Text(
        if (filter == FeedFilter.ALL) {
            "追跡テーマやGitHub repositoryを追加すると、関係する変化がここに届きます。"
        } else {
            "${filter.label}に当てはまるEventはありません。"
        },
        color = Color(0xFF655F69),
        style = MaterialTheme.typography.bodyMedium,
    )
    Spacer(Modifier.height(16.dp))
    if (filter != FeedFilter.ALL) {
        AccessibleOutlinedButton(onClick = { onFilterChange(FeedFilter.ALL) }, modifier = Modifier.fillMaxWidth()) {
            Text("すべての変化を見る")
        }
        Spacer(Modifier.height(8.dp))
    }
    AccessiblePrimaryButton(onClick = onTopicsClick, modifier = Modifier.fillMaxWidth()) { Text("テーマを追加する") }
    Spacer(Modifier.height(8.dp))
    AccessibleOutlinedButton(onClick = onGithubClick, modifier = Modifier.fillMaxWidth()) { Text("GitHubを連携・設定する") }
}

@Composable
internal fun FeedLoadMoreError(message: String) {
    Text(
        message,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 8.dp)
            .semantics { liveRegion = LiveRegionMode.Assertive },
        color = Color(0xFF8F1D18),
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
internal fun EventCard(
    event: FeedEvent,
    onClick: (FeedEvent) -> Unit,
    onFeedback: (String, Feedback) -> Unit,
    onFollow: (String) -> Unit,
) {
    var menuExpanded by remember { mutableStateOf(false) }
    Card(
        modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp).fillMaxWidth().clickable { onClick(event) },
        shape = RoundedCornerShape(22.dp),
        colors = CardDefaults.cardColors(containerColor = if (event.read) Color(0xFFF8F6F4) else Color.White),
        elevation = CardDefaults.cardElevation(defaultElevation = if (event.read) 0.dp else 1.dp),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                StatusPill(event.importance.label, event.importance.color)
                StatusPill(event.relation.label, event.relation.color, pale = true)
                if (event.following) Text("フォロー中", style = MaterialTheme.typography.labelMedium, color = Color(0xFF006A67))
                Spacer(Modifier.weight(1f))
                if (!event.read) Box(Modifier.size(8.dp).clip(CircleShape).background(Color(0xFFB42318)))
            }
            Spacer(Modifier.height(12.dp))
            ReadableTitle(
                event.title,
                lineHeight = 23.sp,
            )
            Spacer(Modifier.height(7.dp))
            ReadableSummary(event.summary)
            FeedDisplayReasonLine(event.displayReason, modifier = Modifier.padding(top = 8.dp))
            Spacer(Modifier.height(12.dp))
            HorizontalDivider(color = Color(0xFFEAE5EC))
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(event.announcedAt, modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelMedium, color = Color(0xFF655F69), maxLines = 2)
                Box {
                    AccessibleIconButton(onClick = { menuExpanded = true }) {
                        Icon(Icons.Default.MoreVert, contentDescription = "Event操作")
                    }
                    DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                        DropdownMenuItem(
                            text = { Text("重要") },
                            onClick = {
                                menuExpanded = false
                                onFeedback(event.id, Feedback.IMPORTANT)
                            },
                        )
                        if (!event.read) {
                            DropdownMenuItem(
                                text = { Text("既読") },
                                onClick = {
                                    menuExpanded = false
                                    onFeedback(event.id, Feedback.READ)
                                },
                            )
                        }
                        DropdownMenuItem(
                            text = { Text("不要") },
                            onClick = {
                                menuExpanded = false
                                onFeedback(event.id, Feedback.NOT_RELEVANT)
                            },
                        )
                        DropdownMenuItem(
                            text = { Text(if (event.following) "フォロー解除" else "フォロー") },
                            onClick = {
                                menuExpanded = false
                                onFollow(event.id)
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
internal fun FeedDisplayReasonLine(
    reason: DisplayReason?,
    modifier: Modifier = Modifier,
) {
    val text = reason?.userFacingTextOrNull() ?: return
    val maxLines = if (LocalDensity.current.fontScale >= AppReadability.LARGE_FONT_SCALE) 3 else 2
    Text(
        text,
        modifier = modifier
            .testTag("feed-display-reason")
            .semantics { contentDescription = "表示理由: $text" },
        color = Color(0xFF655F69),
        style = MaterialTheme.typography.bodySmall,
        maxLines = maxLines,
        overflow = TextOverflow.Ellipsis,
    )
}
