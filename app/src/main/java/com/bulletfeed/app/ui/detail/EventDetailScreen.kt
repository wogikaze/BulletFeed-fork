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
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
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
                title = { AppBarTitle("更新の詳細", fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    AccessibleIconButton(onClick = onBack) {
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
                    UnknownFactsCard(event.unknownFacts)
                    Spacer(Modifier.height(20.dp))
                    CurrentStateCard(event.currentState)
                    Spacer(Modifier.height(12.dp))
                    KnowledgeBootstrapCard(
                        currentState = event.currentState,
                        following = event.following,
                        isSaving = isSavingKnowledgeBootstrap,
                        onMarkCurrentStateKnown = onMarkCurrentStateKnown,
                    )
                    Spacer(Modifier.height(20.dp))
                    DeltaAccordion(event.openedDelta ?: event.latestDelta)
                    event.impacts.forEach { impact ->
                        Spacer(Modifier.height(10.dp))
                        ImpactCard(impact)
                    }
                    Spacer(Modifier.height(22.dp))
                    SectionHeading(
                        "タイムライン",
                        modifier = Modifier.padding(bottom = 8.dp),
                        tag = "event-detail-timeline-heading",
                    )
                    if (event.timeline.isEmpty()) {
                        EmptyDetailSection("時系列情報はありません。")
                    } else {
                        event.timeline.forEach { TimelineEntryCard(it) }
                    }
                    Spacer(Modifier.height(22.dp))
                    SectionHeading(
                        "根拠・情報源",
                        modifier = Modifier.padding(bottom = 8.dp),
                        tag = "event-detail-evidence-heading",
                    )
                    if (event.sources.isEmpty()) {
                        EmptyDetailSection("参照できる情報源はありません。")
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
    Column(Modifier.padding(bottom = 12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatusPill(event.importance.label, event.importance.color)
            StatusPill(event.relation.label, event.relation.color, pale = true)
        }
        FeedDisplayReasonLine(event.displayReason, modifier = Modifier.padding(top = 8.dp))
    }
}

@Composable
internal fun UnknownFactsCard(facts: List<UnknownFact>) {
    SectionHeading(
        if (facts.isEmpty()) "未確認の事実" else "未確認の事実（${facts.size}）",
        modifier = Modifier.padding(bottom = 8.dp),
        tag = "event-detail-unknown-facts-heading",
    )
    if (facts.isEmpty()) {
        EmptyDetailSection("この更新について、未確認の事実はありません。")
        return
    }
    Card(
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(18.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
            facts.forEach { fact ->
                Row(Modifier.padding(vertical = 6.dp).fillMaxWidth()) {
                    Text("・", style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Bold)
                    Text(
                        fact.text,
                        modifier = Modifier.padding(start = 6.dp).testTag("event-detail-unknown-fact"),
                        style = MaterialTheme.typography.bodyLarge,
                        lineHeight = 24.sp,
                    )
                }
            }
        }
    }
}

@Composable
internal fun DeltaAccordion(delta: FeedDelta) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        SectionHeading(
            "前回からの変更",
            modifier = Modifier.padding(bottom = 4.dp),
            tag = "event-detail-delta-heading",
        )
        AccessibleOutlinedButton(
            onClick = { expanded = !expanded },
            modifier = Modifier.fillMaxWidth().testTag("event-detail-delta-toggle"),
        ) {
            Icon(
                imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = null,
                modifier = Modifier.size(18.dp),
            )
            Text(
                if (expanded) "変更前後を閉じる" else "変更前後を表示",
                modifier = Modifier.padding(start = 5.dp),
            )
        }
        if (expanded) {
            Spacer(Modifier.height(8.dp))
            DeltaCard(delta)
        }
    }
}

@Composable
private fun CurrentStateCard(state: CurrentState) =
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFE8F3F1)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text("現在の状態", color = Color(0xFF006A67), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(5.dp))
            Text(state.phaseLabel(), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(state.summary, modifier = Modifier.padding(top = 5.dp), style = MaterialTheme.typography.bodyMedium)
            Text(
                "${state.since} から · 信頼度 ${state.confidence.confidenceLabel()}",
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
            Text(delta.type.label(), color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
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
        Text("${impact.kindLabel()} · 信頼度 ${impact.confidence.confidenceLabel()}", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
        Text(impact.text, modifier = Modifier.padding(top = 3.dp), style = MaterialTheme.typography.bodyMedium)
    }

@Composable
private fun TimelineEntryCard(entry: EventTimelineEntry) =
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text("${entry.occurredAt} · ${entry.type.label()}", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
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
internal fun EventSourceCard(source: EventSource) {
    val uriHandler = LocalUriHandler.current
    Card(
        modifier = Modifier.padding(vertical = 6.dp).fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(15.dp)) {
            Text(
                "${source.publisher} · ${source.kind.label()}",
                color = Color(0xFF1769AA),
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(source.title, modifier = Modifier.padding(top = 3.dp), fontWeight = FontWeight.SemiBold)
            Text("根拠: ${source.evidence}", modifier = Modifier.padding(top = 6.dp), style = MaterialTheme.typography.bodySmall)
            Text(
                "公開: ${source.publishedAt}\n取得: ${source.retrievedAt}",
                modifier = Modifier.padding(top = 7.dp),
                color = Color(0xFF655F69),
                style = MaterialTheme.typography.labelSmall,
            )
            AccessibleTextButton(onClick = { runCatching { uriHandler.openUri(source.url) } }) {
                Icon(Icons.Default.OpenInNew, contentDescription = null, modifier = Modifier.size(17.dp))
                Text("情報源を開く", modifier = Modifier.padding(start = 5.dp))
            }
        }
    }
}

@Composable
internal fun KnowledgeBootstrapCard(
    currentState: CurrentState,
    following: Boolean,
    isSaving: Boolean,
    onMarkCurrentStateKnown: (Boolean) -> Unit,
) = Card(
    colors = CardDefaults.cardColors(containerColor = Color(0xFFF6EFEB)),
    modifier = Modifier.fillMaxWidth(),
) {
    Column(Modifier.padding(16.dp)) {
        SectionHeading(
            "すでに知っている内容を記録",
            style = MaterialTheme.typography.titleMedium,
            tag = "knowledge-bootstrap-heading",
        )
        Text(
            "現在の状態「${currentState.summary}」を、すでに知っている内容として記録できます。",
            modifier = Modifier.padding(top = 6.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = Color(0xFF49454F),
        )
        Text(
            "この状態を既知として記録すると、現時点ですでに成立している事実だけを既知として扱います。途中経過は含めません。",
            modifier = Modifier.padding(top = 8.dp),
            style = MaterialTheme.typography.bodySmall,
            color = Color(0xFF655F69),
        )
        Text(
            "「ここから追跡する」は開始時刻だけを記録し、過去の事実を既知として扱いません。",
            modifier = Modifier.padding(top = 4.dp),
            style = MaterialTheme.typography.bodySmall,
            color = Color(0xFF655F69),
        )
        if (!following) {
            Text(
                "初めてフォローするときにも同じ確認を表示します。",
                modifier = Modifier.padding(top = 6.dp),
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFF655F69),
            )
        }
        Spacer(Modifier.height(12.dp))
        AccessiblePrimaryButton(
            onClick = { onMarkCurrentStateKnown(false) },
            enabled = !isSaving,
            modifier = Modifier.fillMaxWidth().testTag("knowledge-bootstrap-already-knew"),
        ) {
            Text("この状態はすでに知っている")
        }
        Spacer(Modifier.height(8.dp))
        AccessibleOutlinedButton(
            onClick = { onMarkCurrentStateKnown(true) },
            enabled = !isSaving,
            modifier = Modifier.fillMaxWidth().testTag("knowledge-bootstrap-catch-up"),
        ) {
            Text("ここから追跡する")
        }
    }
}

@Composable
internal fun EmptyDetailSection(text: String) =
    Text(
        text,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 14.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
        color = Color(0xFF655F69),
    )

@Composable
internal fun EventActionBar(
    following: Boolean,
    hasFeedContext: Boolean,
    onFeedback: (Feedback) -> Unit,
    onFollow: () -> Unit,
    onDismiss: () -> Unit,
    selectedKnowledge: Feedback? = null,
) {
    var knowledgeSelection by remember(selectedKnowledge) { mutableStateOf(selectedKnowledge) }
    Surface(tonalElevation = 4.dp, shadowElevation = 8.dp, color = Color.White) {
        Column(
            modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (hasFeedContext) {
                    AccessibleTextButton(onClick = onDismiss) {
                        Text("不要", color = Color(0xFF655F69))
                    }
                }
                AccessibleOutlinedButton(onClick = onFollow, modifier = Modifier.weight(1f)) {
                    Icon(
                        imageVector = if (following) Icons.Default.Check else Icons.Default.Add,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Text(if (following) "フォロー中" else "フォロー", modifier = Modifier.padding(start = 5.dp))
                }
                if (hasFeedContext) {
                    AccessiblePrimaryButton(onClick = { onFeedback(Feedback.IMPORTANT) }, modifier = Modifier.weight(1f)) {
                        Icon(Icons.Default.StarBorder, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text("重要", modifier = Modifier.padding(start = 5.dp))
                    }
                }
            }
            if (hasFeedContext) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    KnowledgeChoiceButton(
                        label = "知っていた",
                        selected = knowledgeSelection == Feedback.ALREADY_KNEW,
                        modifier = Modifier.weight(1f).testTag("event-detail-already-knew"),
                        onClick = {
                            knowledgeSelection = Feedback.ALREADY_KNEW
                            onFeedback(Feedback.ALREADY_KNEW)
                        },
                    )
                    KnowledgeChoiceButton(
                        label = "今知った",
                        selected = knowledgeSelection == Feedback.LEARNED_NOW,
                        modifier = Modifier.weight(1f).testTag("event-detail-learned-now"),
                        onClick = {
                            knowledgeSelection = Feedback.LEARNED_NOW
                            onFeedback(Feedback.LEARNED_NOW)
                        },
                    )
                }
                knowledgeSelection?.let { recorded ->
                    Text(
                        if (recorded == Feedback.ALREADY_KNEW) {
                            "「知っていた」を記録しました"
                        } else {
                            "「今知った」を記録しました"
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("event-detail-knowledge-recorded")
                            .semantics { liveRegion = LiveRegionMode.Polite },
                        color = Color(0xFF006A67),
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
    }
}

@Composable
private fun KnowledgeChoiceButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val choiceModifier = modifier.semantics { this.selected = selected }
    if (selected) {
        AccessiblePrimaryButton(onClick = onClick, modifier = choiceModifier) {
            Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(18.dp))
            Text(label, modifier = Modifier.padding(start = 5.dp), fontWeight = FontWeight.Bold)
        }
    } else {
        AccessibleOutlinedButton(onClick = onClick, modifier = choiceModifier) {
            Text(label)
        }
    }
}

private fun DeltaType.label(): String =
    when (this) {
        DeltaType.NEW_FACT -> "新しい事実"
        DeltaType.DETAIL -> "詳細の追加"
        DeltaType.STATE_UPDATE -> "状態の更新"
        DeltaType.CORRECTION -> "訂正"
        DeltaType.UNRESOLVED_CONTRADICTION -> "未解決の矛盾"
    }

private fun TimelineType.label(): String =
    when (this) {
        TimelineType.ANNOUNCED -> "発表"
        TimelineType.STATE_CHANGED -> "状態変更"
        TimelineType.INFORMATION_ADDED -> "情報追加"
        TimelineType.CORRECTED -> "訂正"
        TimelineType.RESOLVED -> "解決"
    }

private fun SourceKind.label(): String =
    when (this) {
        SourceKind.STATUSPAGE -> "Statuspage"
        SourceKind.GITHUB_ADVISORY -> "GitHubセキュリティ情報"
        SourceKind.OSV -> "OSV"
        SourceKind.GITHUB_RELEASE -> "GitHubリリース"
        SourceKind.GITHUB_SBOM -> "GitHub SBOM"
        SourceKind.RSS_ATOM -> "RSS / Atom"
        SourceKind.JSON_FEED -> "JSON Feed"
        SourceKind.OFFICIAL_CHANGELOG -> "公式変更履歴"
        SourceKind.DOCUMENTATION -> "ドキュメント"
    }

private fun EventImpact.kindLabel(): String =
    when (kind.lowercase()) {
        "inferred" -> "推定される影響"
        "explicit" -> "明示された影響"
        else -> "影響"
    }

private fun CurrentState.phaseLabel(): String =
    when (phase.trim().lowercase()) {
        "identified" -> "確認済み"
        "investigating" -> "調査中"
        "monitoring" -> "監視中"
        "resolved" -> "解決済み"
        "released", "shipping", "available" -> "公開済み"
        "prerelease", "release_candidate" -> "公開前"
        "planned", "scheduled" -> "予定"
        "active", "ongoing" -> "進行中"
        "deprecated" -> "非推奨"
        "ended", "closed" -> "終了"
        else -> if (phase.hasJapaneseText()) phase else "現在の状況"
    }

private fun String.confidenceLabel(): String =
    when (trim().lowercase()) {
        "high" -> "高"
        "medium" -> "中"
        "low" -> "低"
        "none" -> "未評価"
        else -> if (hasJapaneseText()) trim() else "未評価"
    }

private fun String.hasJapaneseText(): Boolean =
    any { character ->
        character in '\u3040'..'\u30FF' || character in '\u3400'..'\u9FFF'
    }
