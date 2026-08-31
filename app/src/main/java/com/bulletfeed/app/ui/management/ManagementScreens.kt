package com.bulletfeed.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material3.ButtonDefaults
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyListState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TopicsScreen(
    topics: List<UserTopic>,
    searchResults: List<UserTopic>,
    searchQuery: String,
    isSearching: Boolean,
    githubConnected: Boolean,
    topicSyncMessage: String? = null,
    onGithubClick: () -> Unit,
    onSearchTopics: (String) -> Unit,
    onAddTopic: (String, TopicType) -> Unit,
    onAddSearchResult: (UserTopic) -> Unit,
    onRemoveTopic: (String) -> Unit,
    onPriorityChange: (String, TopicPriority) -> Unit,
    onReorderTopics: (List<String>) -> Unit,
    recommendedTopics: List<TopicRecommendation> = emptyList(),
    onAddRecommendation: (TopicRecommendation) -> Unit = {},
    onIgnoreRecommendation: (String) -> Unit = {},
    modifier: Modifier = Modifier,
) {
    var newTopic by rememberSaveable { mutableStateOf("") }
    var newTopicType by rememberSaveable { mutableStateOf(TopicType.TECHNOLOGY.name) }
    var query by rememberSaveable(searchQuery) { mutableStateOf(searchQuery) }
    val selectedType = TopicType.entries.firstOrNull { it.name == newTopicType } ?: TopicType.TECHNOLOGY
    val topicLimitReached = topics.size >= MAX_TRACKED_TOPICS
    var orderedTopics by remember { mutableStateOf(topics) }
    var dragging by remember { mutableStateOf(false) }
    val lazyListState = rememberLazyListState()
    val headerCount = 1
    val reorderableState = rememberReorderableLazyListState(lazyListState) { from, to ->
        val fromIndex = from.index - headerCount
        val toIndex = to.index - headerCount
        if (fromIndex in orderedTopics.indices && toIndex in orderedTopics.indices) {
            orderedTopics = orderedTopics.toMutableList().apply {
                add(toIndex, removeAt(fromIndex))
            }
        }
    }

    LaunchedEffect(topics) {
        if (dragging) {
            val byId = topics.associateBy { it.id }
            orderedTopics = orderedTopics.map { byId[it.id] ?: it }
        } else {
            orderedTopics = topics
        }
    }

    Scaffold(topBar = { TopAppBar(title = { AppBarTitle("テーマ") }) }) { padding ->
        LazyColumn(
            state = lazyListState,
            modifier = modifier.padding(padding).fillMaxSize().padding(horizontal = 20.dp),
        ) {
            item {
                Spacer(Modifier.height(12.dp))
                SectionHeading("追跡中のテーマ", style = MaterialTheme.typography.headlineSmall)
                Spacer(Modifier.height(6.dp))
                Text("優先度をタップして切り替え · ${topics.size}/$MAX_TRACKED_TOPICS", color = Color(0xFF655F69))
                if (topicLimitReached) {
                    Text(
                        "上限に達しています。別のテーマを追加するには、追跡中のテーマを1件削除してください。",
                        modifier = Modifier.padding(top = 6.dp),
                        color = Color(0xFF8F1D18),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Spacer(Modifier.height(14.dp))
            }
            if (orderedTopics.isEmpty()) {
                item {
                    PoliteEmptyStatus("追跡テーマはまだありません。候補検索か自由入力から追加してください。")
                }
            } else {
                items(orderedTopics, key = { it.id }) { topic ->
                    ReorderableItem(reorderableState, key = topic.id) { isDragging ->
                        TopicManagementCard(
                            topic = topic,
                            dragging = isDragging,
                            dragHandleModifier = Modifier.draggableHandle(
                                onDragStarted = { dragging = true },
                                onDragStopped = {
                                    dragging = false
                                    onReorderTopics(orderedTopics.map { it.id })
                                },
                            ),
                            onPriorityChange = onPriorityChange,
                            onRemoveTopic = onRemoveTopic,
                        )
                    }
                }
            }
            item {
                Spacer(Modifier.height(18.dp))
                Text("おすすめテーマ", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    "検索結果ではなく、興味・履歴から出した推薦です。",
                    color = Color(0xFF655F69),
                    style = MaterialTheme.typography.bodySmall,
                )
                if (recommendedTopics.isEmpty()) {
                    PoliteEmptyStatus("いま出せる推薦はありません。", modifier = Modifier.padding(top = 8.dp))
                }
            }
            items(recommendedTopics, key = { "rec-${it.id}" }) { item ->
                Card(
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFFF6EFEB)),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Text(item.name, fontWeight = FontWeight.Bold)
                        Text(item.reason, color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
                        Text(
                            "出典: ${item.provenance} · 信頼度: ${item.confidence}",
                            color = Color(0xFF655F69),
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Row(Modifier.padding(top = 8.dp)) {
                            AccessiblePrimaryButton(onClick = { onAddRecommendation(item) }, enabled = !topicLimitReached) {
                                Text("追加")
                            }
                            Spacer(Modifier.width(8.dp))
                            AccessibleTextButton(onClick = { onIgnoreRecommendation(item.id) }) { Text("無視") }
                        }
                    }
                }
            }
            item {
                Spacer(Modifier.height(18.dp))
                Text("候補を検索", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    AccessibleOutlinedTextField(
                        value = query,
                        onValueChange = {
                            query = it
                            if (it.isBlank()) onSearchTopics("")
                        },
                        modifier = Modifier.weight(1f).testTag("topic-search-field"),
                        label = { Text("技術・サービス・企業") },
                        singleLine = true,
                    )
                    Spacer(Modifier.width(8.dp))
                    AccessiblePrimaryButton(onClick = { onSearchTopics(query) }, enabled = query.isNotBlank() && !isSearching) {
                        if (isSearching) {
                            CircularProgressIndicator(modifier = Modifier.size(17.dp), strokeWidth = 2.dp)
                        } else {
                            Text("検索")
                        }
                    }
                }
                if (isSearching) {
                    Text("候補を検索中…", modifier = Modifier.padding(top = 8.dp), color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
                }
            }
            items(searchResults, key = { "search-${it.id}" }) { result ->
                Card(
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F3F1)),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(result.name, fontWeight = FontWeight.Bold)
                            Text(result.type.label(), color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
                        }
                        AccessiblePrimaryButton(
                            onClick = { onAddSearchResult(result) },
                            enabled = !topicLimitReached,
                        ) {
                            Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(17.dp))
                            Text(if (topicLimitReached) "上限" else "追加", modifier = Modifier.padding(start = 4.dp))
                        }
                    }
                }
            }
            item {
                Spacer(Modifier.height(22.dp))
                Text("自由入力", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Row(
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TopicType.entries.forEach { type ->
                        AccessibleFilterChip(
                            selected = selectedType == type,
                            onClick = { newTopicType = type.name },
                            label = type.label(),
                            modifier = Modifier.padding(end = 6.dp),
                        )
                    }
                }
                Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    AccessibleOutlinedTextField(
                        value = newTopic,
                        onValueChange = { newTopic = it },
                        modifier = Modifier.weight(1f).testTag("topic-add-field"),
                        label = { Text("テーマを追加") },
                        singleLine = true,
                    )
                    Spacer(Modifier.width(8.dp))
                    AccessiblePrimaryButton(
                        onClick = {
                            onAddTopic(newTopic, selectedType)
                            newTopic = ""
                        },
                        enabled = newTopic.isNotBlank() && !topicLimitReached,
                    ) {
                        Icon(Icons.Default.Add, contentDescription = "追加", modifier = Modifier.size(18.dp))
                    }
                }
                Spacer(Modifier.height(24.dp))
                Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFE8F3F1)), shape = RoundedCornerShape(20.dp)) {
                    Column(Modifier.padding(18.dp)) {
                        Text("GitHub連携", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text(
                            when {
                                !topicSyncMessage.isNullOrBlank() -> topicSyncMessage
                                githubConnected -> "監視するrepositoryを保存すると、使っている技術がこの一覧に追加されます。"
                                else -> "使っている技術を読み取り、あなたに関係する変更をより正確に届けます。"
                            },
                            modifier = Modifier.padding(top = 6.dp),
                            color = Color(0xFF3D5A56),
                        )
                        Spacer(Modifier.height(12.dp))
                        AccessiblePrimaryButton(
                            onClick = onGithubClick,
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF006A67)),
                        ) {
                            Text(if (githubConnected) "連携設定を見る" else "GitHubを連携する")
                        }
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

@Composable
private fun TopicManagementCard(
    topic: UserTopic,
    dragging: Boolean,
    dragHandleModifier: Modifier,
    onPriorityChange: (String, TopicPriority) -> Unit,
    onRemoveTopic: (String) -> Unit,
) = Card(
    modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
    colors = CardDefaults.cardColors(containerColor = Color.White),
    elevation = CardDefaults.cardElevation(defaultElevation = if (dragging) 6.dp else 0.dp),
    shape = RoundedCornerShape(16.dp),
) {
    Row(Modifier.padding(horizontal = 8.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        AccessibleIconButton(onClick = {}, modifier = dragHandleModifier) {
            Icon(Icons.Default.DragHandle, contentDescription = "並び替え", tint = Color(0xFF655F69))
        }
        Column(Modifier.weight(1f)) {
            Text(topic.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(topic.type.label(), color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
        }
        AccessibleAssistChip(
            label = topic.priority.label(),
            onClick = { onPriorityChange(topic.id, topic.priority.next()) },
            labelColor = topic.priority.chipColor(),
        )
        AccessibleTextButton(onClick = { onRemoveTopic(topic.id) }) { Text("削除", color = Color(0xFF8F1D18)) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GithubConnectionScreen(
    connection: GithubConnection,
    repositories: List<GithubRepositoryChoice>,
    nextCursor: String?,
    query: String,
    isLoading: Boolean,
    isLoadingMore: Boolean,
    isSaving: Boolean,
    isAuthorizing: Boolean,
    errorMessage: String?,
    topicSyncMessage: String? = null,
    onBack: () -> Unit,
    onConnect: () -> Unit,
    onSearch: (String) -> Unit,
    onLoadMore: () -> Unit,
    onToggleRepository: (String) -> Unit,
    onSaveRepositories: () -> Unit,
    onImportRepo: (String) -> Unit,
    onDisconnect: () -> Unit,
) {
    var repoInput by rememberSaveable { mutableStateOf("") }
    var searchQuery by rememberSaveable { mutableStateOf(query) }
    BackHandler(onBack = onBack)
    Scaffold(
        topBar = {
            TopAppBar(
                title = { AppBarTitle("GitHub連携") },
                navigationIcon = {
                    AccessibleIconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "戻る")
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize().padding(horizontal = 20.dp)) {
            item {
                Spacer(Modifier.height(12.dp))
                SectionHeading(
                    if (connection.connected) "GitHubを連携済みです" else "GitHubを連携する",
                    style = MaterialTheme.typography.headlineSmall,
                    tag = "github-connection-heading",
                )
                connection.accountLogin?.let {
                    Text("$it として連携中", color = Color(0xFF006A67), modifier = Modifier.padding(top = 5.dp))
                }
                Text(
                    "選択したrepositoryのメタデータと依存関係を関連性判定に利用します。private repositoryは現在のGitHub accessに従います。",
                    modifier = Modifier.padding(top = 8.dp),
                    color = Color(0xFF49454F),
                )
                if (errorMessage != null) {
                    Text(errorMessage, modifier = Modifier.padding(top = 12.dp), color = Color(0xFF8F1D18), style = MaterialTheme.typography.bodySmall)
                }
                if (!topicSyncMessage.isNullOrBlank()) {
                    Text(
                        topicSyncMessage,
                        modifier = Modifier.padding(top = 12.dp),
                        color = Color(0xFF006A67),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                Spacer(Modifier.height(20.dp))
            }
            if (!connection.connected) {
                item {
                    InfoBlock("必要な権限", "公開プロフィールと、選択したrepositoryに対してGitHubが現在許可しているメタデータ・依存関係情報")
                    Spacer(Modifier.height(14.dp))
                    AccessiblePrimaryButton(
                        onClick = onConnect,
                        enabled = !isAuthorizing,
                        modifier = Modifier.fillMaxWidth().testTag("github-authorize-button"),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF24292F)),
                    ) {
                        if (isAuthorizing) {
                            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(8.dp))
                        }
                        Text(if (isAuthorizing) "認可完了を確認中" else "GitHubで認可する")
                    }
                    Spacer(Modifier.height(24.dp))
                    Text("public repositoryからテーマを取り込む", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                    AccessibleOutlinedTextField(
                        value = repoInput,
                        onValueChange = { repoInput = it },
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp).testTag("github-import-repo-field"),
                        label = { Text("owner/repo") },
                        singleLine = true,
                    )
                    AccessiblePrimaryButton(
                        onClick = {
                            onImportRepo(repoInput)
                            repoInput = ""
                        },
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        enabled = repoInput.isNotBlank(),
                    ) {
                        Text("技術・ライブラリを取り込む")
                    }
                }
            } else {
                item {
                    SectionHeading("監視するrepository", tag = "github-repositories-heading")
                    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        AccessibleOutlinedTextField(
                            value = searchQuery,
                            onValueChange = { searchQuery = it },
                            modifier = Modifier.weight(1f).testTag("github-repo-search-field"),
                            label = { Text("repositoryを検索") },
                            singleLine = true,
                        )
                        Spacer(Modifier.width(8.dp))
                        AccessiblePrimaryButton(
                            onClick = { onSearch(searchQuery) },
                            modifier = Modifier.testTag("github-repo-search-button"),
                        ) { Text("検索") }
                    }
                    Spacer(Modifier.height(10.dp))
                }
                if (isLoading) {
                    item {
                        Row(Modifier.fillMaxWidth().padding(24.dp), verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
                            Text("repositoryを取得中", modifier = Modifier.padding(start = 10.dp))
                        }
                    }
                } else if (repositories.isEmpty()) {
                    item { PoliteEmptyStatus("該当するrepositoryはありません。", modifier = Modifier.padding(vertical = 24.dp)) }
                } else {
                    items(repositories, key = { it.id }) { repository ->
                        RepositoryChoiceCard(repository, onToggleRepository)
                    }
                }
                if (nextCursor != null) {
                    item {
                        AccessibleOutlinedButton(
                            onClick = onLoadMore,
                            enabled = !isLoadingMore,
                            modifier = Modifier.fillMaxWidth().padding(top = 10.dp).testTag("github-load-more-button"),
                        ) {
                            if (isLoadingMore) {
                                CircularProgressIndicator(modifier = Modifier.size(17.dp), strokeWidth = 2.dp)
                                Spacer(Modifier.width(8.dp))
                            }
                            Text(if (isLoadingMore) "読み込み中" else "次のページを読み込む")
                        }
                    }
                }
                item {
                    AccessiblePrimaryButton(
                        onClick = onSaveRepositories,
                        enabled = !isSaving,
                        modifier = Modifier.fillMaxWidth().padding(top = 18.dp).testTag("github-save-repositories-button"),
                    ) {
                        if (isSaving) {
                            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(8.dp))
                        }
                        Text(if (isSaving) "保存中" else "選択を保存")
                    }
                    if (!topicSyncMessage.isNullOrBlank()) {
                        Text(
                            topicSyncMessage,
                            modifier = Modifier.padding(top = 10.dp),
                            color = Color(0xFF006A67),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    AccessibleTextButton(
                        onClick = onDisconnect,
                        modifier = Modifier.fillMaxWidth().padding(top = 10.dp).testTag("github-disconnect-button"),
                    ) {
                        Text("GitHub連携を解除", color = Color(0xFF8F1D18))
                    }
                    Spacer(Modifier.height(24.dp))
                }
            }
        }
    }
}

@Composable
internal fun RepositoryChoiceCard(
    repository: GithubRepositoryChoice,
    onToggle: (String) -> Unit,
) = Card(
    modifier = Modifier
        .fillMaxWidth()
        .padding(vertical = 6.dp)
        .defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp)
        .testTag("github-repository-card")
        .clickable { onToggle(repository.id) },
    shape = RoundedCornerShape(16.dp),
    colors = CardDefaults.cardColors(containerColor = Color.White),
) {
    Row(Modifier.padding(15.dp), verticalAlignment = Alignment.CenterVertically) {
        androidx.compose.foundation.layout.Box(
            Modifier.size(24.dp).clip(RoundedCornerShape(6.dp)).background(
                if (repository.selected) Color(0xFF006A67) else Color(0xFFE0DCE3),
            ),
            contentAlignment = Alignment.Center,
        ) {
            if (repository.selected) {
                Icon(Icons.Default.Check, contentDescription = "選択済み", tint = Color.White, modifier = Modifier.size(18.dp))
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(repository.fullName, fontWeight = FontWeight.Bold, maxLines = 3, overflow = TextOverflow.Ellipsis)
            Text(
                listOfNotNull(
                    if (repository.isPrivate) "private" else "public",
                    repository.language,
                    repository.updatedAt.takeIf { it.isNotBlank() },
                ).joinToString(" · "),
                color = Color(0xFF655F69),
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
            )
            repository.description?.let {
                Text(it, modifier = Modifier.padding(top = 3.dp), color = Color(0xFF49454F), style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    profile: UserProfile,
    isSaving: Boolean,
    onSaveProfile: (UserProfile) -> Unit,
    recommendations: List<SourceRecommendation> = emptyList(),
    decidingRecommendationId: String? = null,
    onApproveRecommendation: (String) -> Unit = {},
    onIgnoreRecommendation: (String) -> Unit = {},
    subscriptions: List<SourceSubscription> = emptyList(),
    isSavingSubscription: Boolean = false,
    subscriptionError: String? = null,
    onAddSubscription: (UserSourceKind, String, String) -> Unit = { _, _, _ -> },
    onRemoveSubscription: (String) -> Unit = {},
    siteFeedDiscoverResult: SiteFeedDiscoverResult? = null,
    isDiscoveringSiteFeeds: Boolean = false,
    siteFeedDiscoverError: String? = null,
    onDiscoverSiteFeeds: (String) -> Unit = {},
    knowledgeBootstrap: KnowledgeBootstrapSummary = KnowledgeBootstrapSummary(
        version = "",
        explicitKnownFactCount = 0,
        inferredFactCount = 0,
    ),
    isSavingKnowledgeBootstrap: Boolean = false,
    onResetKnowledgeBootstrap: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    var editing by rememberSaveable { mutableStateOf(false) }
    var role by rememberSaveable(profile.role) { mutableStateOf(profile.role) }
    var interestsText by rememberSaveable(profile.interests) { mutableStateOf(profile.interests.joinToString(", ")) }
    var region by rememberSaveable(profile.region) { mutableStateOf(profile.region) }

    Scaffold(topBar = { TopAppBar(title = { AppBarTitle("設定") }) }) { padding ->
        Column(
            modifier
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            SectionHeading("あなたの情報", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(16.dp))
            if (!editing) {
                InfoBlock("職種", profile.role.ifBlank { "未設定" })
                Spacer(Modifier.height(8.dp))
                InfoBlock("興味", profile.interests.joinToString(" · ").ifBlank { "未設定" })
                Spacer(Modifier.height(8.dp))
                InfoBlock("地域", profile.region.ifBlank { "未設定" })
                Spacer(Modifier.height(20.dp))
                AccessibleOutlinedButton(
                    onClick = {
                        role = profile.role
                        interestsText = profile.interests.joinToString(", ")
                        region = profile.region
                        editing = true
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("プロフィールを編集") }
            } else {
                AccessibleOutlinedTextField(
                    value = role,
                    onValueChange = { role = it },
                    label = { Text("職種") },
                    modifier = Modifier.fillMaxWidth().testTag("profile-role-field"),
                    singleLine = true,
                )
                AccessibleOutlinedTextField(
                    value = interestsText,
                    onValueChange = { interestsText = it },
                    label = { Text("興味（カンマ区切り）") },
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    singleLine = false,
                )
                AccessibleOutlinedTextField(
                    value = region,
                    onValueChange = { region = it },
                    label = { Text("地域") },
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    singleLine = true,
                )
                AccessiblePrimaryButton(
                    onClick = {
                        val interests = interestsText
                            .split(",", "、")
                            .map { it.trim() }
                            .filter { it.isNotEmpty() }
                            .toSet()
                        onSaveProfile(UserProfile(role.trim(), interests, region.trim()))
                        editing = false
                    },
                    enabled = role.isNotBlank() && !isSaving,
                    modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
                ) {
                    if (isSaving) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(if (isSaving) "保存中" else "保存")
                }
                AccessibleTextButton(onClick = { editing = false }, enabled = !isSaving, modifier = Modifier.fillMaxWidth()) {
                    Text("キャンセル")
                }
            }
            Spacer(Modifier.height(28.dp))
            SiteFeedDiscoverSection(
                result = siteFeedDiscoverResult,
                isDiscovering = isDiscoveringSiteFeeds,
                errorMessage = siteFeedDiscoverError,
                isSavingSubscription = isSavingSubscription,
                onDiscover = onDiscoverSiteFeeds,
                onSubscribe = onAddSubscription,
            )
            Spacer(Modifier.height(28.dp))
            SourceSubscriptionsSection(
                subscriptions = subscriptions,
                isSaving = isSavingSubscription,
                errorMessage = subscriptionError,
                onAdd = onAddSubscription,
                onRemove = onRemoveSubscription,
            )
            Spacer(Modifier.height(28.dp))
            KnowledgeBootstrapSection(
                summary = knowledgeBootstrap,
                isSaving = isSavingKnowledgeBootstrap,
                onReset = onResetKnowledgeBootstrap,
            )
            Spacer(Modifier.height(28.dp))
            SourceRecommendationsSection(
                recommendations = recommendations,
                decidingRecommendationId = decidingRecommendationId,
                onApprove = onApproveRecommendation,
                onIgnore = onIgnoreRecommendation,
            )
        }
    }
}

@Composable
private fun KnowledgeBootstrapSection(
    summary: KnowledgeBootstrapSummary,
    isSaving: Boolean,
    onReset: () -> Unit,
) {
    SectionHeading(
        "既存知識の登録",
        style = MaterialTheme.typography.headlineSmall,
        tag = "settings-knowledge-heading",
    )
    Spacer(Modifier.height(8.dp))
    Text(
        "BulletFeed 外ですでに知っている現在状態を、Event / Topic の確認から登録できます。Claim ID を手入力する画面はありません。低信頼の推定（inferred）は非表示に使いません。",
        style = MaterialTheme.typography.bodyMedium,
        color = Color(0xFF655F69),
    )
    Spacer(Modifier.height(8.dp))
    Text(
        "catch up は「これから追う」だけで、現在より前を既知にはしません。現在状態の確認は、その時点ですでに真だった事実だけを既知にします。",
        style = MaterialTheme.typography.bodySmall,
        color = Color(0xFF655F69),
    )
    Spacer(Modifier.height(12.dp))
    InfoBlock("確認済みの現在状態", "${summary.explicitKnownFactCount} 件")
    Spacer(Modifier.height(8.dp))
    InfoBlock("推定（非表示には未使用）", "${summary.inferredFactCount} 件")
    Spacer(Modifier.height(12.dp))
    if (summary.checkpoints.isEmpty()) {
        PoliteEmptyStatus("まだ checkpoint はありません。Event 詳細または初回フォローで登録できます。")
    } else {
        summary.checkpoints.forEach { item ->
            Card(
                colors = CardDefaults.cardColors(containerColor = Color(0xFFF6EFEB)),
                modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text(
                        when (item.subjectKind) {
                            BootstrapSubjectKind.EVENT -> "Event の現在状態"
                            BootstrapSubjectKind.TOPIC -> "Topic の現在状態"
                            BootstrapSubjectKind.GLOBAL -> "全体"
                        },
                        fontWeight = FontWeight.Bold,
                    )
                    Text(item.subjectId, style = MaterialTheme.typography.bodySmall, color = Color(0xFF655F69))
                    Text(
                        if (item.catchUp) {
                            "catch up: 開始時刻のみ。過去は既知にしていません。"
                        } else {
                            "現在より前の真である事実 ${item.knownFactCount} 件を既知にしました。"
                        },
                    )
                }
            }
        }
    }
    AccessibleOutlinedButton(
        onClick = onReset,
        enabled = !isSaving && (summary.checkpoints.isNotEmpty() || summary.explicitKnownFactCount > 0),
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
    ) {
        Text(if (isSaving) "リセット中" else "bootstrap だけをリセット")
    }
}

@Composable
private fun SiteFeedDiscoverSection(
    result: SiteFeedDiscoverResult?,
    isDiscovering: Boolean,
    errorMessage: String?,
    isSavingSubscription: Boolean,
    onDiscover: (String) -> Unit,
    onSubscribe: (UserSourceKind, String, String) -> Unit,
) {
    var siteUrl by rememberSaveable { mutableStateOf("") }
    SectionHeading(
        "サイトからフィードを探す",
        style = MaterialTheme.typography.headlineSmall,
        tag = "settings-site-feed-discover-heading",
    )
    Spacer(Modifier.height(8.dp))
    Text(
        "ブログや公式サイトのトップURLだけを入れると、RSS / Atom / JSON Feed の候補を探します。発見しただけでは購読にも証拠にもなりません。",
        style = MaterialTheme.typography.bodyMedium,
        color = Color(0xFF655F69),
    )
    AccessibleOutlinedTextField(
        value = siteUrl,
        onValueChange = { siteUrl = it },
        label = { Text("サイト URL") },
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 10.dp)
            .testTag("site-feed-discover-url"),
        singleLine = true,
    )
    if (errorMessage != null) {
        SourceSubscriptionErrorStatus(errorMessage)
    }
    AccessiblePrimaryButton(
        onClick = { onDiscover(siteUrl.trim()) },
        enabled = !isDiscovering && siteUrl.isNotBlank(),
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 12.dp)
            .testTag("site-feed-discover-button"),
    ) {
        if (isDiscovering) {
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(8.dp))
        }
        Text(if (isDiscovering) "探しています" else "フィードを探す")
    }
    when {
        result == null -> Unit
        result.items.isEmpty() -> {
            Spacer(Modifier.height(12.dp))
            PoliteEmptyStatus("このサイトから購読できるフィードは見つかりませんでした。下の Web として追加できます。")
        }
        else -> {
            if (result.preferredFamily == "generic_web" || result.items.all { it.family == "generic_web" }) {
                Spacer(Modifier.height(12.dp))
                PoliteEmptyStatus("RSS / Atom / JSON Feed は見つかりませんでした。ページ監視の候補だけを表示しています。")
            }
            result.items.forEach { item ->
                SiteFeedDiscoverCandidateCard(
                    item = item,
                    enabled = !isDiscovering && !isSavingSubscription,
                    onSubscribe = onSubscribe,
                )
                Spacer(Modifier.height(10.dp))
            }
        }
    }
}

@Composable
private fun SiteFeedDiscoverCandidateCard(
    item: SiteFeedDiscoverItem,
    enabled: Boolean,
    onSubscribe: (UserSourceKind, String, String) -> Unit,
) {
    val kind = item.subscriptionKindOrNull()
    val canSubscribe = item.actionability == SourceActionability.SUBSCRIBE
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF6EFEB)),
        modifier = Modifier
            .fillMaxWidth()
            .testTag(if (item.preferred) "site-feed-discover-preferred" else "site-feed-discover-item"),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                item.title.ifBlank { item.canonicalUrl },
                fontWeight = FontWeight.Bold,
            )
            Text(item.canonicalUrl, style = MaterialTheme.typography.bodySmall, color = Color(0xFF655F69))
            Text("種類: ${item.familyLabel()}")
            if (item.preferred) {
                Text("優先候補", fontWeight = FontWeight.Medium)
            }
            if (item.discoveryOnly) {
                Text("発見のみ。購読するまで証拠には使いません。")
            }
            if (!item.evidenceEligible) {
                Text("証拠には未使用", style = MaterialTheme.typography.bodySmall, color = Color(0xFF655F69))
            }
            if (item.explanation.isNotBlank()) {
                Text(item.explanation, style = MaterialTheme.typography.bodySmall, color = Color(0xFF655F69))
            }
            if (kind != null && canSubscribe) {
                AccessiblePrimaryButton(
                    onClick = { onSubscribe(kind, item.canonicalUrl, "") },
                    enabled = enabled,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp)
                        .testTag("site-feed-discover-subscribe"),
                ) {
                    Text(if (kind == UserSourceKind.GENERIC_WEB) "Webとして追加" else "このフィードを購読")
                }
            }
        }
    }
}

internal fun SiteFeedDiscoverItem.subscriptionKindOrNull(): UserSourceKind? =
    when (family) {
        "rss_atom" -> UserSourceKind.RSS_ATOM
        "json_feed" -> UserSourceKind.JSON_FEED
        "generic_web" -> UserSourceKind.GENERIC_WEB
        "statuspage" -> UserSourceKind.STATUSPAGE
        else -> null
    }

private fun SiteFeedDiscoverItem.familyLabel(): String =
    when (family) {
        "rss_atom" -> "RSS / Atom"
        "json_feed" -> "JSON Feed"
        "statuspage" -> "Statuspage"
        "generic_web" -> "Web"
        else -> family
    }

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SourceSubscriptionsSection(
    subscriptions: List<SourceSubscription>,
    isSaving: Boolean,
    errorMessage: String?,
    onAdd: (UserSourceKind, String, String) -> Unit,
    onRemove: (String) -> Unit,
) {
    var kind by rememberSaveable { mutableStateOf(UserSourceKind.RSS_ATOM.name) }
    var url by rememberSaveable { mutableStateOf("") }
    var pageId by rememberSaveable { mutableStateOf("") }
    val selectedKind = UserSourceKind.valueOf(kind)

    SectionHeading(
        "購読中の情報源",
        style = MaterialTheme.typography.headlineSmall,
        tag = "settings-subscriptions-heading",
    )
    Spacer(Modifier.height(8.dp))
    Text(
        "Statuspage / RSS / JSON Feed / Web を追加できます。失敗中の購読は状態を確認してください。",
        style = MaterialTheme.typography.bodyMedium,
        color = Color(0xFF655F69),
    )
    val failingCount = subscriptions.count { it.state == SourceSubscriptionState.FAILING }
    if (failingCount > 0) {
        Spacer(Modifier.height(8.dp))
        SourcePartialFailureStatus(failingCount)
    }
    Spacer(Modifier.height(12.dp))
    if (subscriptions.isEmpty()) {
        PoliteEmptyStatus("まだ購読はありません。")
    } else {
        subscriptions.forEach { item ->
            val failing = item.state == SourceSubscriptionState.FAILING
            Card(
                colors = CardDefaults.cardColors(containerColor = Color(0xFFF6EFEB)),
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .padding(bottom = 10.dp)
                        .testTag(if (failing) "source-subscription-failing" else "source-subscription-ok"),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text(item.publisher?.displayName ?: item.canonicalUrl, fontWeight = FontWeight.Bold)
                    Text(item.canonicalUrl, style = MaterialTheme.typography.bodySmall, color = Color(0xFF655F69))
                    Text("種類: ${item.kindLabel()}")
                    Text(
                        "状態: ${item.state.label()}",
                        color = if (failing) Color(0xFFA6231C) else Color(0xFF655F69),
                        fontWeight = if (failing) FontWeight.Medium else FontWeight.Normal,
                    )
                    if (failing && item.failureCount > 0) {
                        Text(
                            "連続失敗 ${item.failureCount}回",
                            color = Color(0xFFA6231C),
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    AccessibleTextButton(
                        onClick = { onRemove(item.id) },
                        enabled = !isSaving,
                    ) { Text("購読を削除") }
                }
            }
        }
    }
    Spacer(Modifier.height(8.dp))
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        UserSourceKind.entries.forEach { option ->
            AccessibleFilterChip(
                selected = selectedKind == option,
                onClick = { kind = option.name },
                label = option.label(),
            )
        }
    }
    if (selectedKind == UserSourceKind.STATUSPAGE) {
        AccessibleOutlinedTextField(
            value = pageId,
            onValueChange = { pageId = it },
            label = { Text("Statuspage page ID") },
            modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
            singleLine = true,
        )
    }
    AccessibleOutlinedTextField(
        value = url,
        onValueChange = { url = it },
        label = {
            Text(
                when (selectedKind) {
                    UserSourceKind.STATUSPAGE -> "または Statuspage URL"
                    UserSourceKind.GENERIC_WEB -> "Web URL"
                    else -> "フィード URL"
                },
            )
        },
        modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
        singleLine = true,
    )
    if (errorMessage != null) {
        SourceSubscriptionErrorStatus(errorMessage)
    }
    AccessiblePrimaryButton(
        onClick = { onAdd(selectedKind, url.trim(), pageId.trim()) },
        enabled = !isSaving && (url.isNotBlank() || (selectedKind == UserSourceKind.STATUSPAGE && pageId.isNotBlank())),
        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
    ) {
        if (isSaving) {
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(8.dp))
        }
        Text(if (isSaving) "保存中" else "情報源を追加")
    }
}

@Composable
internal fun SourceSubscriptionErrorStatus(message: String) {
    Text(
        message,
        color = Color(0xFFA6231C),
        modifier = Modifier
            .padding(top = 8.dp)
            .semantics { liveRegion = LiveRegionMode.Assertive },
    )
}

@Composable
internal fun SourcePartialFailureStatus(failingCount: Int) {
    Text(
        "${failingCount}件の情報源が失敗中です。他の購読とフィードはそのまま使えます。",
        color = Color(0xFFA6231C),
        style = MaterialTheme.typography.bodyMedium,
        modifier =
            Modifier
                .testTag("source-subscription-partial-failure")
                .semantics { liveRegion = LiveRegionMode.Polite },
    )
}

@Composable
private fun SourceRecommendationsSection(
    recommendations: List<SourceRecommendation>,
    decidingRecommendationId: String?,
    onApprove: (String) -> Unit,
    onIgnore: (String) -> Unit,
) {
    SectionHeading(
        "情報源の候補",
        style = MaterialTheme.typography.headlineSmall,
        tag = "settings-recommendations-heading",
    )
    Spacer(Modifier.height(8.dp))
    Text(
        "興味・テーマから見つけた候補です。承認すると購読できる系統だけが同期されます。",
        style = MaterialTheme.typography.bodyMedium,
        color = Color(0xFF655F69),
    )
    Spacer(Modifier.height(12.dp))
    if (recommendations.isEmpty()) {
        PoliteEmptyStatus("いま表示できる候補はありません。テーマを追加すると候補が増えます。")
        return
    }
    recommendations.forEach { item ->
        SourceRecommendationCard(
            item = item,
            deciding = decidingRecommendationId == item.id,
            enabled = decidingRecommendationId == null,
            onApprove = { onApprove(item.id) },
            onIgnore = { onIgnore(item.id) },
        )
        Spacer(Modifier.height(10.dp))
    }
}

@Composable
private fun SourceRecommendationCard(
    item: SourceRecommendation,
    deciding: Boolean,
    enabled: Boolean,
    onApprove: () -> Unit,
    onIgnore: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF6EFEB)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                item.publisher?.displayName ?: item.canonicalUrl,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(item.canonicalUrl, style = MaterialTheme.typography.bodySmall, color = Color(0xFF655F69))
            Spacer(Modifier.height(8.dp))
            Text(item.reason, fontWeight = FontWeight.Medium)
            if (item.explanation.isNotBlank() && item.explanation != item.reason) {
                Text(item.explanation, style = MaterialTheme.typography.bodyMedium, color = Color(0xFF655F69))
            }
            Spacer(Modifier.height(8.dp))
            Text("系統: ${item.familyLabel()}")
            Text("出典: ${item.discoveryProvenance}")
            Text("権威: ${item.authorityStatus}（信頼度 ${"%.2f".format(item.authorityConfidence)}）")
            Text("状態: ${item.recommendationStatus.label()}")
            Text("操作: ${item.actionability.label()}")
            if (item.discoveryOnly) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "情報発見用です。事実の根拠（truth source）には使いません。",
                    color = Color(0xFFA6231C),
                    fontWeight = FontWeight.Medium,
                )
            }
            if (item.recommendationStatus == SourceRecommendationStatus.PENDING) {
                Spacer(Modifier.height(12.dp))
                Row {
                    if (item.canApprove()) {
                        AccessiblePrimaryButton(
                            onClick = onApprove,
                            enabled = enabled,
                            modifier = Modifier.weight(1f),
                        ) {
                            if (deciding) {
                                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                                Spacer(Modifier.width(8.dp))
                            }
                            Text(item.approveLabel())
                        }
                        Spacer(Modifier.width(8.dp))
                    }
                    AccessibleOutlinedButton(
                        onClick = onIgnore,
                        enabled = enabled,
                        modifier = Modifier.weight(1f),
                    ) { Text("無視") }
                }
            }
        }
    }
}

private fun SourceSubscription.kindLabel(): String =
    when (kind) {
        "rss_atom" -> "RSS / Atom"
        "json_feed" -> "JSON Feed"
        "statuspage" -> "Statuspage"
        else -> kind
    }

private fun SourceSubscriptionState.label(): String =
    when (this) {
        SourceSubscriptionState.PENDING -> "同期待ち"
        SourceSubscriptionState.OK -> "正常"
        SourceSubscriptionState.FAILING -> "失敗中"
    }

private fun UserSourceKind.label(): String =
    when (this) {
        UserSourceKind.STATUSPAGE -> "Statuspage"
        UserSourceKind.RSS_ATOM -> "RSS"
        UserSourceKind.JSON_FEED -> "JSON Feed"
        UserSourceKind.GENERIC_WEB -> "Web"
    }

private fun SourceRecommendation.familyLabel(): String =
    when (family) {
        "rss_atom" -> "RSS / Atom"
        "json_feed" -> "JSON Feed"
        "statuspage" -> "Statuspage"
        "github_release" -> "GitHub Releases"
        "generic_web" -> "Web"
        "hacker_news_discovery" -> "Hacker News（発見用）"
        else -> family
    }

private fun SourceRecommendationStatus.label(): String =
    when (this) {
        SourceRecommendationStatus.PENDING -> "未決定"
        SourceRecommendationStatus.APPROVED -> "承認済み"
        SourceRecommendationStatus.IGNORED -> "無視"
    }

private fun SourceActionability.label(): String =
    when (this) {
        SourceActionability.SUBSCRIBE -> "購読できる"
        SourceActionability.SELECT_REPOSITORY -> "リポジトリ選択へ"
        SourceActionability.DISCOVERY_ONLY -> "発見のみ（承認不可）"
        SourceActionability.UNSUPPORTED -> "未接続（承認不可）"
    }

private fun SourceRecommendation.approveLabel(): String =
    when (actionability) {
        SourceActionability.SELECT_REPOSITORY -> "リポジトリ候補として記録"
        else -> "購読する"
    }

private fun TopicType.label(): String =
    when (this) {
        TopicType.TECHNOLOGY -> "技術"
        TopicType.SERVICE -> "サービス"
        TopicType.COMPANY -> "企業"
    }

private fun TopicPriority.label(): String =
    when (this) {
        TopicPriority.HIGH -> "高"
        TopicPriority.NORMAL -> "標準"
        TopicPriority.LOW -> "低"
    }

private fun TopicPriority.next(): TopicPriority =
    when (this) {
        TopicPriority.HIGH -> TopicPriority.NORMAL
        TopicPriority.NORMAL -> TopicPriority.LOW
        TopicPriority.LOW -> TopicPriority.HIGH
    }

private fun TopicPriority.chipColor(): Color =
    when (this) {
        TopicPriority.HIGH -> Color(0xFFA6231C)
        TopicPriority.NORMAL -> Color(0xFF655F69)
        TopicPriority.LOW -> Color(0xFF9A9590)
    }
