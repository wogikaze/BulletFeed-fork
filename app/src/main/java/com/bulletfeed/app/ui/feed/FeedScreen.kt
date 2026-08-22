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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

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
    modifier: Modifier = Modifier,
) {
    val activeEvents = events.filterNot { it.dismissed }
    val visibleEvents =
        activeEvents
            .filter { event ->
                when (filter) {
                    FeedFilter.ALL -> true
                    FeedFilter.DIRECT -> event.relation == Relation.DIRECT
                    FeedFilter.ADJACENT -> event.relation == Relation.ADJACENT
                    FeedFilter.REFERENCE -> event.relation == Relation.REFERENCE
                }
            }.sortedWith(
                compareByDescending<FeedEvent> { event ->
                    event.importance == Importance.CRITICAL || event.importance == Importance.HIGH
                }.thenBy { event -> event.read },
            )
    val urgentEvents =
        activeEvents.filter { event ->
            !event.read && (event.importance == Importance.CRITICAL || event.importance == Importance.HIGH)
        }
    val directUnreadCount = activeEvents.count { event -> !event.read && event.relation == Relation.DIRECT }

    LazyColumn(modifier = modifier.fillMaxSize()) {
        item {
            TopAppBar(
                title = {
                    Column {
                        Text("BulletFeed", fontWeight = FontWeight.Bold)
                        Text(
                            "あなたに関係する変化を整理",
                            style = MaterialTheme.typography.labelMedium,
                            color = Color(0xFF655A6D),
                        )
                    }
                },
                actions = {
                    IconButton(onClick = onNotificationsClick) {
                        if (unreadNotificationCount > 0) {
                            BadgedBox(
                                badge = {
                                    Badge { Text(unreadNotificationCount.coerceAtMost(99).toString()) }
                                },
                            ) {
                                Icon(Icons.Default.Notifications, contentDescription = "通知を開く")
                            }
                        } else {
                            Icon(Icons.Default.Notifications, contentDescription = "通知を開く")
                        }
                    }
                    Text(
                        "LIVE",
                        modifier =
                            Modifier
                                .padding(end = 20.dp)
                                .clip(RoundedCornerShape(50))
                                .background(Color(0xFFE8F3F1))
                                .padding(horizontal = 9.dp, vertical = 5.dp),
                        color = Color(0xFF006A67),
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.Bold,
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFFFFFBF8)),
            )
            TodaySummary(
                urgentEvents = urgentEvents,
                directUnreadCount = directUnreadCount,
                onEventClick = onEventClick,
            )
            if (securityActionCount > 0) {
                SecurityShortcut(
                    actionCount = securityActionCount,
                    onClick = onSecurityClick,
                )
            }
            FilterRow(filter, activeEvents, onFilterChange)
            FeedHeading(filter, visibleEvents.size)
        }
        if (visibleEvents.isEmpty()) {
            item { EmptyFeed(filter) }
        } else {
            items(visibleEvents, key = { it.id }) { event ->
                EventCard(
                    event = event,
                    onClick = onEventClick,
                    onFeedback = onFeedback,
                    onFollow = onFollow,
                )
            }
        }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@Composable
private fun SecurityShortcut(
    actionCount: Int,
    onClick: () -> Unit,
) = Card(
    modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp).fillMaxWidth().clickable(onClick = onClick),
    colors = CardDefaults.cardColors(containerColor = Color(0xFFFCE8E6)),
    shape = RoundedCornerShape(18.dp),
) {
    Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier.size(38.dp).clip(CircleShape).background(Color(0xFFB42318)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.Security, contentDescription = null, tint = Color.White, modifier = Modifier.size(22.dp))
        }
        Column(Modifier.padding(start = 11.dp).weight(1f)) {
            Text("脆弱性への対応が $actionCount 件必要です", fontWeight = FontWeight.Bold, color = Color(0xFF8F1D18))
            Text("影響するリポジトリと修正版を確認", color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
        }
        Icon(
            Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = "セキュリティを開く",
            tint = Color(0xFFB42318),
        )
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
            Box(
                Modifier.size(36.dp).clip(CircleShape).background(Color(0xFFC83C32)),
                contentAlignment = Alignment.Center,
            ) {
                Text("!", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp)
            }
            Spacer(Modifier.width(11.dp))
            Column {
                Text("今日の優先順位", color = Color.White, fontWeight = FontWeight.Bold)
                Text(
                    "直接影響の未読が $directUnreadCount 件",
                    color = Color(0xFFFFDAD5),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Spacer(Modifier.weight(1f))
            Text(
                "${urgentEvents.size}件",
                color = Color.White,
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
            )
        }
        urgentEvents.firstOrNull()?.let { event ->
            Spacer(Modifier.height(16.dp))
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(16.dp))
                    .background(Color.White.copy(alpha = 0.12f))
                    .clickable { onEventClick(event) }
                    .padding(13.dp),
            ) {
                Text("最優先 · ${event.relation.label}", color = Color(0xFFFFD8A8), style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(3.dp))
                Text(
                    event.title,
                    color = Color.White,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(6.dp))
                Text("確認する", color = Color(0xFFFFDAD5), style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

@Composable
private fun FilterRow(
    selected: FeedFilter,
    events: List<FeedEvent>,
    onSelect: (FeedFilter) -> Unit,
) = LazyRow(
    modifier = Modifier.fillMaxWidth(),
    contentPadding =
        androidx.compose.foundation.layout
            .PaddingValues(horizontal = 20.dp, vertical = 8.dp),
    horizontalArrangement = Arrangement.spacedBy(8.dp),
) {
    items(FeedFilter.entries) { item ->
        val count =
            when (item) {
                FeedFilter.ALL -> events.size
                FeedFilter.DIRECT -> events.count { it.relation == Relation.DIRECT }
                FeedFilter.ADJACENT -> events.count { it.relation == Relation.ADJACENT }
                FeedFilter.REFERENCE -> events.count { it.relation == Relation.REFERENCE }
            }
        FilterChip(
            selected = selected == item,
            onClick = { onSelect(item) },
            label = { Text("${item.label} $count") },
        )
    }
}

@Composable
private fun FeedHeading(
    filter: FeedFilter,
    count: Int,
) = Row(
    modifier = Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 4.dp),
    verticalAlignment = Alignment.CenterVertically,
) {
    Text("${filter.label}の変化", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    Spacer(Modifier.weight(1f))
    Text("${count}件", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
}

@Composable
private fun EmptyFeed(filter: FeedFilter) =
    Column(Modifier.fillMaxWidth().padding(36.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text("表示する変化はありません", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        Text(
            "${filter.label}に当てはまる未処理のイベントはありません。",
            color = Color(0xFF655F69),
            style = MaterialTheme.typography.bodyMedium,
        )
    }

@Composable
private fun EventCard(
    event: FeedEvent,
    onClick: (FeedEvent) -> Unit,
    onFeedback: (String, Feedback) -> Unit,
    onFollow: (String) -> Unit,
) = Card(
    modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp).fillMaxWidth().clickable { onClick(event) },
    shape = RoundedCornerShape(22.dp),
    colors = CardDefaults.cardColors(containerColor = if (event.read) Color(0xFFF8F6F4) else Color.White),
    elevation = CardDefaults.cardElevation(defaultElevation = if (event.read) 0.dp else 1.dp),
) {
    Column(Modifier.padding(16.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            StatusPill(event.importance.label, event.importance.color)
            StatusPill(event.relation.label, event.relation.color, pale = true)
            if (event.following) {
                Text("フォロー中", style = MaterialTheme.typography.labelMedium, color = Color(0xFF006A67))
            }
            Spacer(Modifier.weight(1f))
            if (!event.read) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(Color(0xFFB42318)))
            }
        }
        Spacer(Modifier.height(12.dp))
        Text(event.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, lineHeight = 23.sp)
        Spacer(Modifier.height(7.dp))
        Text(
            event.summary,
            style = MaterialTheme.typography.bodyMedium,
            color = Color(0xFF49454F),
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(Modifier.height(13.dp))
        ImpactReason(event)
        Spacer(Modifier.height(12.dp))
        HorizontalDivider(color = Color(0xFFEAE5EC))
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${event.announcedAt}  ·  根拠 ${event.sourceCount}件",
                style = MaterialTheme.typography.labelMedium,
                color = Color(0xFF655F69),
            )
            Spacer(Modifier.weight(1f))
            Row(
                modifier = Modifier.clickable { onFeedback(event.id, Feedback.IMPORTANT) }.padding(4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val importanceColor = if (event.markedImportant) Color(0xFFD55A00) else Color(0xFF655F69)
                Icon(
                    imageVector = if (event.markedImportant) Icons.Default.Star else Icons.Default.StarBorder,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = importanceColor,
                )
                Text("重要", color = importanceColor, style = MaterialTheme.typography.labelMedium)
            }
            Row(
                modifier = Modifier.clickable { onFollow(event.id) }.padding(4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = if (event.following) Icons.Default.Check else Icons.Default.Add,
                    contentDescription = if (event.following) "フォロー中" else "フォローする",
                    modifier = Modifier.size(20.dp),
                    tint = Color(0xFF006A67),
                )
            }
        }
    }
}

@Composable
private fun ImpactReason(event: FeedEvent) =
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(event.relation.color.copy(alpha = 0.08f))
            .padding(horizontal = 10.dp, vertical = 9.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            Modifier
                .padding(top = 5.dp)
                .size(6.dp)
                .clip(CircleShape)
                .background(event.relation.color),
        )
        Spacer(Modifier.width(8.dp))
        Column {
            Text("なぜあなたに関係する？", color = event.relation.color, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            Text(
                event.relationReason,
                color = Color(0xFF49454F),
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
