package com.bulletfeed.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EventDetailScreen(event: FeedEvent, onBack: () -> Unit, onFeedback: (Feedback) -> Unit, onFollow: () -> Unit) {
    Scaffold(topBar = { TopAppBar(title = { Text("イベント詳細") }, navigationIcon = { Text("‹", modifier = Modifier.clickable(onClick = onBack).padding(18.dp), fontSize = 30.sp) }) }) { padding ->
        LazyColumn(modifier = Modifier.padding(padding).fillMaxSize()) {
            item {
                Column(Modifier.padding(20.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { StatusPill(event.importance.label, event.importance.color); StatusPill(event.relation.label, event.relation.color, true) }
                    Spacer(Modifier.height(16.dp))
                    Text(event.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, lineHeight = 30.sp)
                    Spacer(Modifier.height(12.dp))
                    Text(event.summary, style = MaterialTheme.typography.bodyLarge, color = Color(0xFF49454F))
                    Spacer(Modifier.height(20.dp))
                    InfoBlock("あなたとの関係", event.relationReason)
                    Spacer(Modifier.height(12.dp))
                    InfoBlock("重要度の理由", event.importanceReason)
                    Spacer(Modifier.height(24.dp))
                    SectionTitle("何が変わったか")
                    ChangeBlock("変更前", event.before, Color(0xFF655F69))
                    Spacer(Modifier.height(8.dp))
                    ChangeBlock("変更後", event.after, Color(0xFF006A67))
                    Spacer(Modifier.height(24.dp))
                    SectionTitle("影響")
                    ImpactBlock("公式に明示された影響", event.explicitImpact, Color(0xFF4A2A7A))
                    event.inferredImpact?.let { Spacer(Modifier.height(8.dp)); ImpactBlock("推定される影響", it, Color(0xFF8A5A00)) }
                    Spacer(Modifier.height(24.dp))
                    SectionTitle("時系列")
                    event.timeline.forEach { TimelineRow(it) }
                    Spacer(Modifier.height(20.dp))
                    SectionTitle("根拠ソース")
                    event.sources.forEach { SourceBlock(it) }
                    Spacer(Modifier.height(20.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = { onFeedback(Feedback.IMPORTANT) }, modifier = Modifier.weight(1f)) { Text(if (event.markedImportant) "重要を解除" else "重要") }
                        OutlinedButton(onClick = onFollow, modifier = Modifier.weight(1f)) { Text(if (event.following) "フォロー中" else "フォロー") }
                    }
                    Text("不要", modifier = Modifier.align(Alignment.CenterHorizontally).clickable { onFeedback(Feedback.NOT_RELEVANT); onBack() }.padding(16.dp), color = Color(0xFF655F69), style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

@Composable
private fun SectionTitle(text: String) = Text(text, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
