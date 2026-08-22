package com.bulletfeed.app

import androidx.compose.animation.AnimatedVisibility
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
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EventDetailScreen(
    event: FeedEvent,
    onBack: () -> Unit,
    onFeedback: (Feedback) -> Unit,
    onFollow: () -> Unit,
) {
    var evidenceExpanded by remember { mutableStateOf(false) }
    androidx.activity.compose.BackHandler(onBack = onBack)

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("変化の詳細", fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "戻る")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFFFFFBF8)),
            )
        },
        bottomBar = {
            EventActionBar(
                event = event,
                onFeedback = onFeedback,
                onFollow = onFollow,
                onDismiss = {
                    onFeedback(Feedback.NOT_RELEVANT)
                    onBack()
                },
            )
        },
    ) { padding ->
        LazyColumn(modifier = Modifier.padding(padding).fillMaxSize()) {
            item {
                Column(Modifier.padding(horizontal = 20.dp, vertical = 10.dp)) {
                    DetailHeader(event)
                    Spacer(Modifier.height(16.dp))
                    PersonalImpactCard(event)
                    Spacer(Modifier.height(20.dp))
                    CompactSectionTitle("何が変わった？")
                    ChangeComparison(event)
                    Spacer(Modifier.height(16.dp))
                    ImportanceReason(event)
                    event.inferredImpact?.let { inferredImpact ->
                        Spacer(Modifier.height(10.dp))
                        InferredImpact(inferredImpact)
                    }
                    Spacer(Modifier.height(18.dp))
                    EvidenceSection(
                        event = event,
                        expanded = evidenceExpanded,
                        onToggle = { evidenceExpanded = !evidenceExpanded },
                    )
                    Spacer(Modifier.height(20.dp))
                }
            }
        }
    }
}

@Composable
private fun DetailHeader(event: FeedEvent) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        StatusPill(event.importance.label, event.importance.color)
        StatusPill(event.relation.label, event.relation.color, pale = true)
        Spacer(Modifier.weight(1f))
        Text(event.announcedAt, color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
    }
    Spacer(Modifier.height(12.dp))
    Text(
        event.title,
        style = MaterialTheme.typography.headlineSmall,
        fontWeight = FontWeight.Bold,
        lineHeight = 30.sp,
    )
    Spacer(Modifier.height(8.dp))
    Text(event.summary, style = MaterialTheme.typography.bodyLarge, color = Color(0xFF49454F), lineHeight = 24.sp)
}

@Composable
private fun PersonalImpactCard(event: FeedEvent) =
    Card(
        colors = CardDefaults.cardColors(containerColor = event.relation.color.copy(alpha = 0.09f)),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(9.dp).clip(CircleShape).background(event.relation.color))
                Spacer(Modifier.size(9.dp))
                Text(
                    "あなたへの影響",
                    color = event.relation.color,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(Modifier.height(9.dp))
            Text(event.explicitImpact, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(10.dp))
            HorizontalDivider(color = event.relation.color.copy(alpha = 0.18f))
            Spacer(Modifier.height(10.dp))
            Text("表示理由", color = Color(0xFF655A6D), style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(3.dp))
            Text(event.relationReason, style = MaterialTheme.typography.bodyMedium, color = Color(0xFF49454F))
        }
    }

@Composable
private fun ChangeComparison(event: FeedEvent) =
    Card(
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(18.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(15.dp)) {
            Text("変更前", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            Text(event.before, style = MaterialTheme.typography.bodyMedium, color = Color(0xFF49454F))
            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                HorizontalDivider(Modifier.weight(1f), color = Color(0xFFE5E0E7))
                Text("  ↓  ", color = Color(0xFF006A67), fontWeight = FontWeight.Bold)
                HorizontalDivider(Modifier.weight(1f), color = Color(0xFFE5E0E7))
            }
            Text("変更後", color = Color(0xFF006A67), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            Text(event.after, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
        }
    }

@Composable
private fun ImportanceReason(event: FeedEvent) =
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(event.importance.color.copy(alpha = 0.08f))
            .padding(13.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text("${event.importance.label}の理由", color = event.importance.color, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
        Spacer(Modifier.size(10.dp))
        Text(event.importanceReason, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = Color(0xFF49454F))
    }

@Composable
private fun InferredImpact(text: String) =
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Color(0xFFFFF4DD))
            .padding(13.dp),
    ) {
        Text("AIによる影響推定", color = Color(0xFF8A5A00), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(3.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = Color(0xFF49454F))
    }

@Composable
private fun EvidenceSection(
    event: FeedEvent,
    expanded: Boolean,
    onToggle: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F3F1)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column {
            Row(
                modifier = Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("経緯と根拠", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    Text(
                        "時系列 ${event.timeline.size}件 · ソース ${event.sources.size}件",
                        color = Color(0xFF655F69),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (expanded) "閉じる" else "見る", color = Color(0xFF1769AA), style = MaterialTheme.typography.labelLarge)
                    Icon(
                        imageVector = if (expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                        contentDescription = null,
                        tint = Color(0xFF1769AA),
                    )
                }
            }
            AnimatedVisibility(visible = expanded) {
                Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp)) {
                    HorizontalDivider(color = Color(0xFFE2DEDB))
                    event.timeline.forEach { TimelineRow(it) }
                    Spacer(Modifier.height(6.dp))
                    event.sources.forEach { SourceBlock(it) }
                }
            }
        }
    }
}

@Composable
private fun EventActionBar(
    event: FeedEvent,
    onFeedback: (Feedback) -> Unit,
    onFollow: () -> Unit,
    onDismiss: () -> Unit,
) {
    Surface(tonalElevation = 4.dp, shadowElevation = 8.dp, color = Color.White) {
        Row(
            modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 12.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onDismiss) { Text("不要", color = Color(0xFF655F69)) }
            OutlinedButton(onClick = onFollow, modifier = Modifier.weight(1f)) {
                Icon(
                    imageVector = if (event.following) Icons.Default.Check else Icons.Default.Add,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.size(6.dp))
                Text(if (event.following) "フォロー中" else "フォロー")
            }
            Button(onClick = { onFeedback(Feedback.IMPORTANT) }, modifier = Modifier.weight(1f)) {
                Icon(
                    imageVector = if (event.markedImportant) Icons.Default.Star else Icons.Default.StarBorder,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.size(6.dp))
                Text("重要")
            }
        }
    }
}

@Composable
private fun CompactSectionTitle(text: String) =
    Text(
        text,
        modifier = Modifier.padding(bottom = 8.dp),
        style = MaterialTheme.typography.titleLarge,
        fontWeight = FontWeight.Bold,
    )
