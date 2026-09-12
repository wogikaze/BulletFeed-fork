package com.bulletfeed.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(
    events: List<FeedEvent>,
    onEventClick: (FeedEvent) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: EventSearchViewModel = viewModel(factory = EventSearchViewModel.Factory(LocalContext.current)),
) {
    @Suppress("UNUSED_VARIABLE")
    val loadedFeedEvents = events
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    Scaffold(topBar = { TopAppBar(title = { AppBarTitle("情報を検索") }) }) { padding ->
        LazyColumn(modifier = modifier.padding(padding).fillMaxSize().padding(horizontal = 20.dp)) {
            item {
                Spacer(Modifier.height(12.dp))
                SectionHeading("すべての追跡履歴を探す", style = MaterialTheme.typography.headlineSmall)
                Text(
                    "現在のフィードだけでなく、アクセスできる過去の更新も検索できます。",
                    color = Color(0xFF655F69),
                    modifier = Modifier.padding(top = 6.dp),
                )
                Spacer(Modifier.height(16.dp))
                AccessibleOutlinedTextField(
                    value = state.query,
                    onValueChange = viewModel::search,
                    modifier = Modifier.fillMaxWidth().testTag("search-query-field"),
                    singleLine = true,
                    label = { Text("例: Cloudflare、料金、Kotlin") },
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = "検索") },
                    shape = RoundedCornerShape(18.dp),
                )
                Spacer(Modifier.height(16.dp))
                Text(
                    if (state.query.isBlank()) "最近の更新" else "検索結果",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(4.dp))
            }

            if (state.isLoading) {
                item {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 28.dp)
                            .semantics { liveRegion = LiveRegionMode.Polite },
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator()
                    }
                }
            } else if (state.errorMessage != null && state.results.isEmpty()) {
                val errorMessage = state.errorMessage ?: "検索を完了できませんでした。"
                item {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 28.dp)
                            .semantics { liveRegion = LiveRegionMode.Polite },
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(errorMessage, color = Color(0xFF8F1D18))
                        Button(
                            onClick = viewModel::retry,
                            modifier = Modifier
                                .padding(top = 12.dp)
                                .defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp),
                        ) {
                            Text("再試行")
                        }
                    }
                }
            } else if (state.results.isEmpty()) {
                item { SearchEmptyResults() }
            } else {
                items(state.results, key = { it.id }) { event ->
                    SearchResultCard(event) { onEventClick(event.toSearchFeedEvent()) }
                }
                state.errorMessage?.let { message ->
                    item {
                        Text(
                            message,
                            color = Color(0xFF8F1D18),
                            modifier = Modifier
                                .padding(vertical = 10.dp)
                                .semantics { liveRegion = LiveRegionMode.Polite },
                        )
                    }
                }
                if (state.nextCursor != null) {
                    item {
                        Button(
                            onClick = viewModel::loadMore,
                            enabled = !state.isLoadingMore,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 16.dp)
                                .defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp),
                        ) {
                            if (state.isLoadingMore) {
                                CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp))
                            }
                            Text(if (state.isLoadingMore) "読み込み中" else "さらに読み込む")
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun SearchEmptyResults() {
    Text(
        "一致する更新はありません。別の言葉で検索してください。",
        color = Color(0xFF655F69),
        modifier = Modifier.padding(vertical = 28.dp).semantics {
            liveRegion = LiveRegionMode.Polite
        },
    )
}

internal fun searchResultMeta(event: EventSearchItem): String =
    event.sourcePublisher
        ?.let { "${event.updatedAt}  ·  $it" }
        ?: event.updatedAt

internal fun EventSearchItem.toSearchFeedEvent(): FeedEvent =
    FeedEvent(
        id = id,
        title = title,
        summary = summary,
        importance = Importance.LOW,
        importanceReason = "検索結果",
        relation = Relation.REFERENCE,
        relationReason = "追跡履歴の検索結果",
        announcedAt = updatedAt,
        sourceCount = if (sourcePublisher == null) 0 else 1,
        before = "",
        after = currentSummary,
        explicitImpact = currentSummary,
        inferredImpact = null,
        sources = sourcePublisher?.let { listOf(Source(it, title, currentSummary)) } ?: emptyList(),
        timeline = emptyList(),
        following = following,
        feedItemId = "",
    )

@Composable
internal fun SearchResultCard(
    event: EventSearchItem,
    onClick: () -> Unit,
) = Card(
    modifier = Modifier
        .fillMaxWidth()
        .padding(vertical = 6.dp)
        .defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp)
        .testTag("search-result-card")
        .clickable(onClick = onClick),
    colors = CardDefaults.cardColors(containerColor = Color.White),
    shape = RoundedCornerShape(18.dp),
    elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
) {
    Column(Modifier.padding(15.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatusPill(event.currentPhase, Color(0xFF5F6368), pale = true)
            if (event.following) StatusPill("フォロー中", Color(0xFFA6231C), pale = true)
        }
        Spacer(Modifier.height(10.dp))
        ReadableTitle(event.title)
        ReadableSummary(event.summary, modifier = Modifier.padding(top = 5.dp))
        if (event.currentSummary.isNotBlank() && event.currentSummary != event.summary) {
            Text(
                event.currentSummary,
                modifier = Modifier.padding(top = 5.dp),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                color = Color(0xFF655F69),
            )
        }
        Text(
            searchResultMeta(event),
            modifier = Modifier.padding(top = 10.dp),
            color = Color(0xFF655F69),
            style = MaterialTheme.typography.labelMedium,
        )
    }
}
