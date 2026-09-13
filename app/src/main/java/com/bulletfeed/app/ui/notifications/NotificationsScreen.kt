package com.bulletfeed.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.DoneAll
import androidx.compose.material.icons.filled.NewReleases
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NotificationsScreen(
    notifications: List<AppNotification>,
    onBack: () -> Unit,
    onNotificationClick: (AppNotification) -> Unit,
    onMarkAllRead: () -> Unit,
) {
    var filter by remember { mutableStateOf(NotificationFilter.UNREAD) }
    val visibleNotifications =
        notifications
            .filter { filter == NotificationFilter.ALL || !it.read }
            .sortedWith(compareBy<AppNotification> { it.read }.thenBy { it.priority.ordinal })
    val unreadCount = notifications.count { !it.read }

    BackHandler(onBack = onBack)
    Scaffold(
        topBar = {
            TopAppBar(
                title = { AppBarTitle("通知", fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    AccessibleIconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "戻る")
                    }
                },
                actions = {
                    if (unreadCount > 0) {
                        AccessibleTextButton(onClick = onMarkAllRead) {
                            Icon(Icons.Default.DoneAll, contentDescription = null, modifier = Modifier.size(18.dp))
                            Text("すべて既読にする", modifier = Modifier.padding(start = 4.dp))
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFFFFFBF8)),
            )
        },
    ) { padding ->
        LazyColumn(modifier = Modifier.padding(padding).fillMaxSize()) {
            item {
                NotificationSummary(unreadCount)
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    NotificationFilter.entries.forEach { item ->
                        val count = if (item == NotificationFilter.UNREAD) unreadCount else notifications.size
                        AccessibleFilterChip(
                            selected = filter == item,
                            onClick = { filter = item },
                            label = "${item.label} $count",
                        )
                    }
                }
            }
            if (visibleNotifications.isEmpty()) {
                item { NotificationEmptyState(filter) }
            } else {
                items(visibleNotifications, key = { it.id }) { notification ->
                    NotificationCard(notification, onClick = { onNotificationClick(notification) })
                }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun NotificationSummary(unreadCount: Int) =
    Card(
        modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp).fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = if (unreadCount > 0) Color(0xFFFFF1D8) else Color(0xFFE8F3F1)),
        shape = RoundedCornerShape(22.dp),
    ) {
        Row(Modifier.padding(17.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier =
                    Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(if (unreadCount > 0) Color(0xFFD55A00) else Color(0xFF006A67)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.Notifications, contentDescription = null, tint = Color.White)
            }
            Column(Modifier.padding(start = 13.dp)) {
                Text(
                    if (unreadCount > 0) "未確認の更新が $unreadCount 件あります" else "すべて確認済みです",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "重要度とあなたへの影響をもとに通知しています。",
                    color = Color(0xFF655F69),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }

@Composable
internal fun NotificationCard(
    notification: AppNotification,
    onClick: () -> Unit,
) = Card(
    modifier = Modifier
        .padding(horizontal = 20.dp, vertical = 6.dp)
        .fillMaxWidth()
        .defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp)
        .testTag("notification-card")
        .clickable(onClick = onClick),
    colors = CardDefaults.cardColors(containerColor = if (notification.read) Color(0xFFF8F6F4) else Color.White),
    shape = RoundedCornerShape(20.dp),
    elevation = CardDefaults.cardElevation(defaultElevation = if (notification.read) 0.dp else 1.dp),
) {
    Row(Modifier.padding(15.dp), verticalAlignment = Alignment.Top) {
        Box(
            modifier =
                Modifier
                    .size(42.dp)
                    .clip(CircleShape)
                    .background(notification.category.color.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector =
                    when (notification.category) {
                        NotificationCategory.SECURITY -> Icons.Default.Security
                        NotificationCategory.BREAKING_CHANGE -> Icons.Default.Warning
                        NotificationCategory.RELEASE -> Icons.Default.NewReleases
                    },
                contentDescription = null,
                tint = notification.category.color,
                modifier = Modifier.size(22.dp),
            )
        }
        Column(Modifier.padding(start = 12.dp).weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    notification.category.label,
                    color = notification.category.color,
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.weight(1f))
                Text(notification.occurredAt, color = Color(0xFF655F69), style = MaterialTheme.typography.labelSmall)
            }
            ReadableTitle(
                notification.title,
                modifier = Modifier.padding(top = 5.dp),
            )
            ReadableSummary(
                notification.summary,
                modifier = Modifier.padding(top = 5.dp),
            )
            HorizontalDivider(modifier = Modifier.padding(top = 11.dp, bottom = 7.dp), color = Color(0xFFEAE5EC))
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (!notification.read) {
                    Box(Modifier.size(7.dp).clip(CircleShape).background(Color(0xFFB42318)))
                    Text("未読", modifier = Modifier.padding(start = 5.dp), color = Color(0xFFB42318), style = MaterialTheme.typography.labelMedium)
                } else {
                    Text("確認済み", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
                }
                Spacer(Modifier.weight(1f))
                Text("詳細を見る", color = notification.category.color, style = MaterialTheme.typography.labelMedium)
                Icon(
                    Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = null,
                    tint = notification.category.color,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
    }
}

@Composable
internal fun NotificationEmptyState(filter: NotificationFilter) =
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(48.dp)
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(Icons.Default.DoneAll, contentDescription = null, tint = Color(0xFF006A67), modifier = Modifier.size(44.dp))
        Spacer(Modifier.height(10.dp))
        Text(if (filter == NotificationFilter.UNREAD) "未読通知はありません" else "通知はありません", fontWeight = FontWeight.Bold)
        Text("重要な更新が届くと、ここに表示されます。", color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
    }
