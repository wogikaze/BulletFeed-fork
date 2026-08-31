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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(
    events: List<FeedEvent>,
    onEventClick: (FeedEvent) -> Unit,
    modifier: Modifier = Modifier,
) {
    var query by remember { mutableStateOf("") }
    val results =
        events.filter { event ->
            !event.dismissed &&
                (
                    query.isBlank() ||
                        listOf(
                            event.title,
                            event.summary,
                            event.relationReason,
                            event.importanceReason,
                            event.relation.label,
                            event.importance.label,
                        ).plus(event.sources.flatMap { listOf(it.publisher, it.title, it.evidence) })
                            .any { it.contains(query, ignoreCase = true) }
                )
        }
    Scaffold(topBar = { TopAppBar(title = { AppBarTitle("情報を検索") }) }) { padding ->
        LazyColumn(modifier = modifier.padding(padding).fillMaxSize().padding(horizontal = 20.dp)) {
            item {
                Spacer(Modifier.height(12.dp))
                Text("追跡中の変化を探す", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("テーマ、企業、技術、イベント内容、情報源から検索できます。", color = Color(0xFF655F69), modifier = Modifier.padding(top = 6.dp))
                Spacer(Modifier.height(16.dp))
                OutlinedTextField(query, {
                    query = it
                }, Modifier.fillMaxWidth(), singleLine = true, label = {
                    Text("例: Cloudflare、料金、Kotlin")
                }, leadingIcon = { Icon(Icons.Default.Search, contentDescription = "検索") }, shape = RoundedCornerShape(18.dp))
                Spacer(Modifier.height(16.dp))
                Text(
                    if (query.isBlank()) "最近のイベント" else "${results.size}件の検索結果",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(4.dp))
            }
            if (results.isEmpty()) {
                item {
                    Text(
                        "一致するイベントはありません。別の言葉で検索してください。",
                        color = Color(0xFF655F69),
                        modifier = Modifier.padding(vertical = 28.dp).semantics {
                            liveRegion = LiveRegionMode.Polite
                        },
                    )
                }
            } else {
                items(results, key = { it.id }) { event -> SearchResultCard(event) { onEventClick(event) } }
            }
        }
    }
}

internal fun searchResultMeta(event: FeedEvent): String =
    event.sources.firstOrNull()?.publisher
        ?.let { "${event.announcedAt}  ·  $it" }
        ?: event.announcedAt

@Composable
private fun SearchResultCard(
    event: FeedEvent,
    onClick: () -> Unit,
) = Card(
    modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp).clickable(onClick = onClick),
    colors = CardDefaults.cardColors(containerColor = Color.White),
    shape = RoundedCornerShape(18.dp),
    elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
) {
    Column(Modifier.padding(15.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatusPill(event.importance.label, event.importance.color)
            StatusPill(event.relation.label, event.relation.color, pale = true)
        }
        Spacer(Modifier.height(10.dp))
        val fontScale = LocalDensity.current.fontScale
        Text(
            event.title,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.titleMedium,
            maxLines = AppReadability.titleMaxLines(fontScale),
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            event.summary,
            modifier = Modifier.padding(top = 5.dp),
            maxLines = AppReadability.summaryMaxLines(fontScale),
            overflow = TextOverflow.Ellipsis,
            color = Color(0xFF49454F),
        )
        Text(
            searchResultMeta(event),
            modifier = Modifier.padding(top = 10.dp),
            color = Color(0xFF655F69),
            style = MaterialTheme.typography.labelMedium,
        )
    }
}
