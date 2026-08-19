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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
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
    events: List<FeedEvent>, filter: FeedFilter, onFilterChange: (FeedFilter) -> Unit,
    onEventClick: (FeedEvent) -> Unit, onFeedback: (String, Feedback) -> Unit,
    onFollow: (String) -> Unit, modifier: Modifier = Modifier
) {
    val visibleEvents = events.filter { event ->
        !event.dismissed && when (filter) {
            FeedFilter.ALL -> true
            FeedFilter.DIRECT -> event.relation == Relation.DIRECT
            FeedFilter.ADJACENT -> event.relation == Relation.ADJACENT
            FeedFilter.REFERENCE -> event.relation == Relation.REFERENCE
        }
    }.sortedWith(compareByDescending<FeedEvent> { it.importance == Importance.CRITICAL || it.importance == Importance.HIGH }.thenBy { it.read })

    LazyColumn(modifier = modifier.fillMaxSize()) {
        item {
            TopAppBar(
                title = { Column { Text("BulletFeed", fontWeight = FontWeight.Bold); Text("あなたに関係する変化", style = MaterialTheme.typography.labelMedium, color = Color(0xFF605A66)) } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFFFFFBFF))
            )
            AlertBanner(events.count { !it.dismissed && !it.read && (it.importance == Importance.CRITICAL || it.importance == Importance.HIGH) })
            FilterRow(filter, onFilterChange)
            Text("フィード", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.padding(20.dp, 16.dp, 20.dp, 8.dp))
        }
        items(visibleEvents, key = { it.id }) { event -> EventCard(event, onEventClick, onFeedback, onFollow) }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@Composable
private fun AlertBanner(count: Int) = Card(modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp).fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFFF8E9DC)), shape = RoundedCornerShape(20.dp)) {
    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(34.dp).clip(CircleShape).background(Color(0xFFC65D00)), contentAlignment = Alignment.Center) { Text("!", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp) }
        Spacer(Modifier.width(12.dp))
        Column { Text("要対応", fontWeight = FontWeight.Bold); Text("$count 件の重要な変化があります", color = Color(0xFF684B32), style = MaterialTheme.typography.bodyMedium) }
    }
}

@Composable
private fun FilterRow(selected: FeedFilter, onSelect: (FeedFilter) -> Unit) = Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
    FeedFilter.entries.forEach { item -> FilterChip(selected = selected == item, onClick = { onSelect(item) }, label = { Text(item.label) }) }
}

@Composable
private fun EventCard(event: FeedEvent, onClick: (FeedEvent) -> Unit, onFeedback: (String, Feedback) -> Unit, onFollow: (String) -> Unit) = Card(
    modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp).fillMaxWidth().clickable { onClick(event) }, shape = RoundedCornerShape(22.dp),
    colors = CardDefaults.cardColors(containerColor = if (event.read) Color(0xFFF8F5F9) else Color.White), elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
) {
    Column(Modifier.padding(16.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            StatusPill(event.importance.label, event.importance.color)
            StatusPill(event.relation.label, event.relation.color, pale = true)
            if (event.following) Text("フォロー中", style = MaterialTheme.typography.labelMedium, color = Color(0xFF006A67))
            Spacer(Modifier.weight(1f))
            if (!event.read) Box(Modifier.size(8.dp).clip(CircleShape).background(Color(0xFF7B3FB5)))
        }
        Spacer(Modifier.height(12.dp))
        Text(event.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, lineHeight = 23.sp)
        Spacer(Modifier.height(7.dp))
        Text(event.summary, style = MaterialTheme.typography.bodyMedium, color = Color(0xFF49454F), maxLines = 2, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(12.dp))
        Text("表示理由  ${event.relationReason}", style = MaterialTheme.typography.labelMedium, color = Color(0xFF655A6D), maxLines = 2, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(12.dp))
        HorizontalDivider(color = Color(0xFFEAE5EC))
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("${event.announcedAt}  ·  根拠 ${event.sourceCount}件", style = MaterialTheme.typography.labelMedium, color = Color(0xFF655F69))
            Spacer(Modifier.weight(1f))
            Text(if (event.markedImportant) "★ 重要" else "☆ 重要", modifier = Modifier.clickable { onFeedback(event.id, Feedback.IMPORTANT) }.padding(4.dp), color = if (event.markedImportant) Color(0xFFC65D00) else Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
            Text(if (event.following) " ✓" else " ＋", modifier = Modifier.clickable { onFollow(event.id) }.padding(4.dp), color = Color(0xFF006A67), style = MaterialTheme.typography.labelMedium)
        }
    }
}
