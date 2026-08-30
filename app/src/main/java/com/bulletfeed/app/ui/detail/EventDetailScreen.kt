package com.bulletfeed.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.OpenInNew
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EventDetailScreen(
    event: EventDetail,
    feedContext: FeedEvent?,
    onBack: () -> Unit,
    onFeedback: (Feedback) -> Unit,
    onFollow: () -> Unit,
    onMarkCurrentStateKnown: (catchUp: Boolean) -> Unit = {},
    isSavingKnowledgeBootstrap: Boolean = false,
) {
    BackHandler(onBack = onBack)
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
                following = event.following,
                hasFeedContext = feedContext != null,
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
                    feedContext?.let { FeedContextHeader(it) }
                    Text(
                        event.title,
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                        lineHeight = 30.sp,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(event.summary, style = MaterialTheme.typography.bodyLarge, color = Color(0xFF49454F), lineHeight = 24.sp)
                    Spacer(Modifier.height(18.dp))
                    CurrentStateCard(event.currentState)
                    Spacer(Modifier.height(12.dp))
                    KnowledgeBootstrapCard(
                        currentState = event.currentState,
                        following = event.following,
                        isSaving = isSavingKnowledgeBootstrap,
                        onMarkCurrentStateKnown = onMarkCurrentStateKnown,
                    )
                    Spacer(Modifier.height(20.dp))
                    SectionTitle("Delta")
                    DeltaCard(event.openedDelta ?: event.latestDelta)
                    event.impacts.forEach { impact ->
                        Spacer(Modifier.height(10.dp))
                        ImpactCard(impact)
                    }
                    Spacer(Modifier.height(22.dp))
                    SectionTitle("Timeline")
                    if (event.timeline.isEmpty()) {
                        EmptyDetailSection("時系列情報はありません。")
                    } else {
                        event.timeline.forEach { TimelineEntryCard(it) }
                    }
                    Spacer(Modifier.height(22.dp))
                    SectionTitle("Evidence / Source")
                    if (event.sources.isEmpty()) {
                        EmptyDetailSection("追跡できるソースはありません。")
                    } else {
                        event.sources.forEach { EventSourceCard(it) }
                    }
                    Spacer(Modifier.height(24.dp))
                }
            }
        }
    }
}

@Composable
private fun FeedContextHeader(event: FeedEvent) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 12.dp)) {
        StatusPill(event.importance.label, event.importance.color)
        StatusPill(event.relation.label, event.relation.color, pale = true)
    }
}

@Composable
private fun CurrentStateCard(state: CurrentState) =
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFE8F3F1)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text("Current state", color = Color(0xFF006A67), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(5.dp))
            Text(state.phase, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(state.summary, modifier = Modifier.padding(top = 5.dp), style = MaterialTheme.typography.bodyMedium)
            Text(
                "since ${state.since} · confidence ${state.confidence}",
                modifier = Modifier.padding(top = 8.dp),
                color = Color(0xFF655F69),
                style = MaterialTheme.typography.labelMedium,
            )
        }
    }

@Composable
private fun DeltaCard(delta: FeedDelta) =
    Card(
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(18.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(15.dp)) {
            Text(delta.type.name.lowercase(), color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
            Text(delta.summary, modifier = Modifier.padding(top = 4.dp), fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(12.dp))
            Text("変更前", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
            Text(delta.before, style = MaterialTheme.typography.bodyMedium)
            HorizontalDivider(Modifier.padding(vertical = 10.dp), color = Color(0xFFE5E0E7))
            Text("変更後", color = Color(0xFF006A67), style = MaterialTheme.typography.labelMedium)
            Text(delta.after, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
            Text(delta.occurredAt, modifier = Modifier.padding(top = 10.dp), color = Color(0xFF655F69), style = MaterialTheme.typography.labelSmall)
        }
    }

@Composable
private fun ImpactCard(impact: EventImpact) =
    Column(
        Modifier
            .fillMaxWidth()
            .background(
                color = if (impact.kind == "inferred") Color(0xFFFFF4DD) else Color(0xFFF5F3F1),
                shape = RoundedCornerShape(14.dp),
            ).padding(13.dp),
    ) {
        Text("${impact.kind} · confidence ${impact.confidence}", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
        Text(impact.text, modifier = Modifier.padding(top = 3.dp), style = MaterialTheme.typography.bodyMedium)
    }

@Composable
private fun TimelineEntryCard(entry: EventTimelineEntry) =
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text("${entry.occurredAt} · ${entry.type.name.lowercase()}", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
        Text(entry.title, modifier = Modifier.padding(top = 2.dp), fontWeight = FontWeight.Bold)
        Text(entry.description, modifier = Modifier.padding(top = 2.dp), style = MaterialTheme.typography.bodyMedium)
        if (entry.stateBefore != null || entry.stateAfter != null) {
            Text(
                "${entry.stateBefore.orEmpty()} → ${entry.stateAfter.orEmpty()}",
                modifier = Modifier.padding(top = 5.dp),
                color = Color(0xFF006A67),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }

@Composable
private fun EventSourceCard(source: EventSource) {
    val uriHandler = LocalUriHandler.current
    Card(
        modifier = Modifier.padding(vertical = 6.dp).fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(15.dp)) {
            Text(
                "${source.publisher} · ${source.kind.name.lowercase()}",
                color = Color(0xFF1769AA),
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(source.title, modifier = Modifier.padding(top = 3.dp), fontWeight = FontWeight.SemiBold)
            Text("根拠: ${source.evidence}", modifier = Modifier.padding(top = 6.dp), style = MaterialTheme.typography.bodySmall)
            Text(
                "published ${source.publishedAt}\nretrieved ${source.retrievedAt}",
                modifier = Modifier.padding(top = 7.dp),
                color = Color(0xFF655F69),
                style = MaterialTheme.typography.labelSmall,
            )
            TextButton(onClick = { runCatching { uriHandler.openUri(source.url) } }) {
                Icon(Icons.Default.OpenInNew, contentDescription = null, modifier = Modifier.size(17.dp))
                Text("元ソースを開く", modifier = Modifier.padding(start = 5.dp))
            }
        }
    }
}

@Composable
private fun KnowledgeBootstrapCard(
    currentState: CurrentState,
    following: Boolean,
    isSaving: Boolean,
    onMarkCurrentStateKnown: (Boolean) -> Unit,
) = Card(
    colors = CardDefaults.cardColors(containerColor = Color(0xFFF6EFEB)),
    modifier = Modifier.fillMaxWidth(),
) {
    Column(Modifier.padding(16.dp)) {
        Text("アプリ外ですでに知っている場合", fontWeight = FontWeight.Bold)
        Text(
            "現在状態「${currentState.summary}」を確認して登録します。Claim ID の入力は不要です。",
            modifier = Modifier.padding(top = 6.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = Color(0xFF49454F),
        )
        Text(
            "「現在より前を既知にする」は、この時点ですでに真だった事実だけを既知にします。途中経過は既知にしません。",
            modifier = Modifier.padding(top = 8.dp),
            style = MaterialTheme.typography.bodySmall,
            color = Color(0xFF655F69),
        )
        Text(
            "「これから追う（catch up）」は開始時刻だけを残し、過去の事実は既知にしません。後から同じ再掲を隠す用途には使いません。",
            modifier = Modifier.padding(top = 4.dp),
            style = MaterialTheme.typography.bodySmall,
            color = Color(0xFF655F69),
        )
        if (!following) {
            Text(
                "初回フォロー時にも同じ確認が開きます。",
                modifier = Modifier.padding(top = 6.dp),
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFF655F69),
            )
        }
        Button(
            onClick = { onMarkCurrentStateKnown(false) },
            enabled = !isSaving,
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
        ) {
            Text("この現在状態はすでに知っている")
        }
        OutlinedButton(
            onClick = { onMarkCurrentStateKnown(true) },
            enabled = !isSaving,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        ) {
            Text("これから追う（過去は既知にしない）")
        }
    }
}

@Composable
private fun EmptyDetailSection(text: String) =
    Text(text, modifier = Modifier.fillMaxWidth().padding(vertical = 14.dp), color = Color(0xFF655F69))

@Composable
private fun SectionTitle(text: String) =
    Text(text, modifier = Modifier.padding(bottom = 8.dp), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)

@Composable
private fun EventActionBar(
    following: Boolean,
    hasFeedContext: Boolean,
    onFeedback: (Feedback) -> Unit,
    onFollow: () -> Unit,
    onDismiss: () -> Unit,
) = Surface(tonalElevation = 4.dp, shadowElevation = 8.dp, color = Color.White) {
    Row(
        modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 12.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (hasFeedContext) {
            TextButton(onClick = onDismiss) { Text("不要", color = Color(0xFF655F69)) }
        }
        OutlinedButton(onClick = onFollow, modifier = Modifier.weight(1f)) {
            Icon(
                imageVector = if (following) Icons.Default.Check else Icons.Default.Add,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
            )
            Text(if (following) "フォロー中" else "フォロー", modifier = Modifier.padding(start = 5.dp))
        }
        if (hasFeedContext) {
            Button(onClick = { onFeedback(Feedback.IMPORTANT) }, modifier = Modifier.weight(1f)) {
                Icon(Icons.Default.StarBorder, contentDescription = null, modifier = Modifier.size(18.dp))
                Text("重要", modifier = Modifier.padding(start = 5.dp))
            }
        }
    }
}
