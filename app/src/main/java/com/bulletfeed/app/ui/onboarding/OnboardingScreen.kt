package com.bulletfeed.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Topic
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp

private const val MINIMUM_TOPIC_COUNT = 5

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun OnboardingScreen(
    initialProfile: UserProfile,
    initialTopics: List<String>,
    isSaving: Boolean,
    onComplete: (UserProfile, List<String>, Boolean) -> Unit,
    recommendedTopics: List<TopicRecommendation> = emptyList(),
    onIgnoreRecommendation: (String) -> Unit = {},
) {
    var step by rememberSaveable { mutableIntStateOf(0) }
    var role by rememberSaveable { mutableStateOf(initialProfile.role.ifBlank { "Androidエンジニア" }) }
    var interests by remember {
        mutableStateOf(initialProfile.interests.ifEmpty { setOf("モバイル", "AI", "クラウド") })
    }
    var region by rememberSaveable { mutableStateOf(initialProfile.region.ifBlank { "東京" }) }
    var topics by remember { mutableStateOf(initialTopics.distinct()) }
    var customTopic by rememberSaveable { mutableStateOf("") }
    var connectGithub by rememberSaveable { mutableStateOf(true) }

    val canContinue =
        when (step) {
            0 -> role.isNotBlank() && interests.isNotEmpty()
            1 -> true
            else -> connectGithub || topics.size >= MINIMUM_TOPIC_COUNT
        }

    BackHandler(enabled = step > 0) { step -= 1 }
    Scaffold(
        topBar = { OnboardingHeader(step = step) },
        bottomBar = {
            OnboardingActions(
                step = step,
                canContinue = canContinue,
                isSaving = isSaving,
                connectGithub = connectGithub,
                onBack = { step -= 1 },
                onNext = {
                    if (step < 2) {
                        step += 1
                    } else {
                        onComplete(
                            UserProfile(role = role, interests = interests, region = region),
                            topics,
                            connectGithub,
                        )
                    }
                },
            )
        },
        containerColor = Color(0xFFFFFBF8),
    ) { padding ->
        LazyColumn(
            modifier = Modifier.padding(padding).fillMaxSize().imePadding(),
            contentPadding =
                androidx.compose.foundation.layout.PaddingValues(
                    horizontal = 20.dp,
                    vertical = 14.dp,
                ),
        ) {
            item {
                when (step) {
                    0 ->
                        ProfileStep(
                            role = role,
                            interests = interests,
                            region = region,
                            onRoleChange = { role = it },
                            onInterestToggle = { interest ->
                                interests =
                                    if (interest in interests) {
                                        interests - interest
                                    } else {
                                        interests + interest
                                    }
                            },
                            onRegionChange = { region = it },
                        )

                    1 ->
                        GithubStep(
                            connectGithub = connectGithub,
                            onSelectionChange = { connectGithub = it },
                        )

                    else ->
                        TopicsStep(
                            topics = topics,
                            customTopic = customTopic,
                            connectGithub = connectGithub,
                            recommendedTopics = recommendedTopics,
                            onIgnoreRecommendation = onIgnoreRecommendation,
                            onCustomTopicChange = { customTopic = it },
                            onToggle = { topic ->
                                topics = if (topic in topics) topics - topic else topics + topic
                            },
                            onAddCustom = {
                                val topic = customTopic.trim()
                                if (topic.isNotEmpty() && topic !in topics) topics = topics + topic
                                customTopic = ""
                            },
                        )
                }
            }
        }
    }
}

@Composable
private fun OnboardingHeader(step: Int) =
    Surface(color = Color(0xFFFFFBF8)) {
        Column(Modifier.statusBarsPadding().padding(horizontal = 20.dp, vertical = 16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("BulletFeed", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Spacer(Modifier.weight(1f))
                Text("${step + 1} / 3", color = Color(0xFF655F69), fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                repeat(3) { index ->
                    Box(
                        Modifier
                            .weight(1f)
                            .height(5.dp)
                            .clip(CircleShape)
                            .background(if (index <= step) Color(0xFFA6231C) else Color(0xFFE4D9D5)),
                    )
                }
            }
        }
    }

@Composable
private fun OnboardingActions(
    step: Int,
    canContinue: Boolean,
    isSaving: Boolean,
    connectGithub: Boolean,
    onBack: () -> Unit,
    onNext: () -> Unit,
) = Surface(tonalElevation = 3.dp, color = Color.White) {
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 16.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (step > 0) {
            OutlinedButton(onClick = onBack, enabled = !isSaving, modifier = Modifier.weight(0.7f)) {
                Text("戻る")
            }
        }
        Button(
            onClick = onNext,
            enabled = canContinue && !isSaving,
            modifier = Modifier.weight(1.3f),
        ) {
            if (isSaving) {
                CircularProgressIndicator(
                    modifier = Modifier.size(18.dp),
                    strokeWidth = 2.dp,
                    color = Color.White,
                )
            } else {
                val label =
                    when {
                        step < 2 -> "次へ"
                        connectGithub -> "GitHubから自動設定を始める"
                        else -> "BulletFeedを始める"
                    }
                Text(label)
                Icon(
                    Icons.AutoMirrored.Filled.ArrowForward,
                    contentDescription = null,
                    modifier = Modifier.padding(start = 6.dp).size(18.dp),
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ProfileStep(
    role: String,
    interests: Set<String>,
    region: String,
    onRoleChange: (String) -> Unit,
    onInterestToggle: (String) -> Unit,
    onRegionChange: (String) -> Unit,
) {
    StepTitle(
        icon = { Icon(Icons.Default.Person, contentDescription = null, tint = Color.White) },
        title = "あなたについて教えてください",
        description = "職種と興味は、repositoryから推定した技術の優先順位付けにも利用します。",
    )
    SelectionLabel("職種")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        roleOptions.forEach { option ->
            FilterChip(
                selected = role == option,
                onClick = { onRoleChange(option) },
                label = { Text(option) },
            )
        }
    }
    SelectionLabel("興味のある分野")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        interestOptions.forEach { option ->
            FilterChip(
                selected = option in interests,
                onClick = { onInterestToggle(option) },
                label = { Text(option) },
                leadingIcon =
                    if (option in interests) {
                        { Icon(Icons.Default.Check, null, Modifier.size(16.dp)) }
                    } else {
                        null
                    },
            )
        }
    }
    SelectionLabel("地域（任意）")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        regionOptions.forEach { option ->
            FilterChip(
                selected = region == option,
                onClick = { onRegionChange(option) },
                label = { Text(option) },
            )
        }
    }
}

@Composable
private fun GithubStep(
    connectGithub: Boolean,
    onSelectionChange: (Boolean) -> Unit,
) {
    StepTitle(
        icon = { Icon(Icons.Default.Code, contentDescription = null, tint = Color.White) },
        title = "追跡テーマの作り方",
        description = "GitHubを連携すると、repositoryを選ぶだけで使用技術・サービスを自動選定します。",
    )
    GithubChoiceCard(
        selected = connectGithub,
        title = "GitHubから自動選定する",
        description =
            "認可後にrepositoryを選択します。言語、GitHub Topics、依存関係、manifest、CI/CD、infra設定からテーマを推定します。",
        onClick = { onSelectionChange(true) },
    )
    Spacer(Modifier.height(10.dp))
    GithubChoiceCard(
        selected = !connectGithub,
        title = "手動でテーマを選ぶ",
        description = "GitHubを使わず、次の画面で5件以上のテーマを選択します。",
        onClick = { onSelectionChange(false) },
    )
    Spacer(Modifier.height(18.dp))
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F3F1)),
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text("repositoryから読むもの", fontWeight = FontWeight.Bold)
            HorizontalDivider(Modifier.padding(vertical = 10.dp), color = Color(0xFFE0D8D4))
            Text(
                "Languages / GitHub Topics / package.json / pyproject・requirements / Gradle / Cargo / go.mod / Maven / Docker / GitHub Actions / Terraform などを読み取ります。",
                color = Color(0xFF655F69),
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                "認可トークンはバックエンドだけで保持し、選択したrepositoryだけを解析します。",
                modifier = Modifier.padding(top = 8.dp),
                color = Color(0xFF655F69),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TopicsStep(
    topics: List<String>,
    customTopic: String,
    connectGithub: Boolean,
    recommendedTopics: List<TopicRecommendation>,
    onIgnoreRecommendation: (String) -> Unit,
    onCustomTopicChange: (String) -> Unit,
    onToggle: (String) -> Unit,
    onAddCustom: () -> Unit,
) {
    StepTitle(
        icon = { Icon(Icons.Default.Topic, contentDescription = null, tint = Color.White) },
        title = if (connectGithub) "最初から追いたいテーマ（任意）" else "追いかけるテーマを選択",
        description =
            if (connectGithub) {
                "ここは空でも開始できます。GitHub認可後にrepositoryを選ぶと、実際の構成からテーマを自動追加します。"
            } else {
                "技術・サービス・企業を5件以上選んでください。あとから変更できます。"
            },
    )
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors =
            CardDefaults.cardColors(
                containerColor =
                    if (connectGithub || topics.size >= MINIMUM_TOPIC_COUNT) {
                        Color(0xFFE8F3F1)
                    } else {
                        Color(0xFFFFF1D8)
                    },
            ),
        shape = RoundedCornerShape(16.dp),
    ) {
        val message =
            when {
                connectGithub && topics.isEmpty() -> "repo選択後に自動選定します"
                connectGithub -> "${topics.size}件を初期テーマとして追加し、repoからさらに自動選定します"
                topics.size >= MINIMUM_TOPIC_COUNT -> "${topics.size}件を追跡します"
                else -> "あと${MINIMUM_TOPIC_COUNT - topics.size}件選択してください"
            }
        Text(
            message,
            modifier = Modifier.padding(14.dp),
            color =
                if (connectGithub || topics.size >= MINIMUM_TOPIC_COUNT) {
                    Color(0xFF006A67)
                } else {
                    Color(0xFF8A5A00)
                },
            fontWeight = FontWeight.Bold,
        )
    }
    if (recommendedTopics.isNotEmpty()) {
        SelectionLabel("おすすめ（推薦API）")
        recommendedTopics.filter { it.name !in topics }.forEach { item ->
            Card(
                modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
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
                    Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { onToggle(item.name) }) { Text("追加") }
                        OutlinedButton(onClick = { onIgnoreRecommendation(item.id) }) { Text("無視") }
                    }
                }
            }
        }
    }
    SelectionLabel("スターター候補")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        starterTopics.forEach { topic ->
            FilterChip(
                selected = topic in topics,
                onClick = { onToggle(topic) },
                label = { Text(topic) },
                leadingIcon =
                    if (topic in topics) {
                        { Icon(Icons.Default.Check, null, Modifier.size(16.dp)) }
                    } else {
                        null
                    },
            )
        }
    }
    SelectionLabel("自由入力")
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedTextField(
            value = customTopic,
            onValueChange = onCustomTopicChange,
            modifier = Modifier.weight(1f),
            label = { Text("企業・技術・サービス") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { onAddCustom() }),
        )
        OutlinedButton(onClick = onAddCustom, enabled = customTopic.isNotBlank()) {
            Icon(Icons.Default.Add, contentDescription = "追加")
        }
    }
}

@Composable
private fun GithubChoiceCard(
    selected: Boolean,
    title: String,
    description: String,
    onClick: () -> Unit,
) = Card(
    modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    colors = CardDefaults.cardColors(containerColor = if (selected) Color(0xFFE8F3F1) else Color.White),
    shape = RoundedCornerShape(20.dp),
    border =
        androidx.compose.foundation.BorderStroke(
            2.dp,
            if (selected) Color(0xFF006A67) else Color(0xFFE0D8D4),
        ),
) {
    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier =
                Modifier
                    .size(28.dp)
                    .clip(CircleShape)
                    .background(if (selected) Color(0xFF006A67) else Color(0xFFE0D8D4)),
            contentAlignment = Alignment.Center,
        ) {
            if (selected) {
                Icon(
                    Icons.Default.Check,
                    contentDescription = "選択済み",
                    tint = Color.White,
                    modifier = Modifier.size(19.dp),
                )
            }
        }
        Column(Modifier.padding(start = 12.dp)) {
            Text(title, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
            Text(
                description,
                modifier = Modifier.padding(top = 4.dp),
                color = Color(0xFF655F69),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun StepTitle(
    icon: @Composable () -> Unit,
    title: String,
    description: String,
) {
    Box(
        modifier =
            Modifier
                .size(50.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(Color(0xFFA6231C)),
        contentAlignment = Alignment.Center,
    ) {
        icon()
    }
    Spacer(Modifier.height(14.dp))
    Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    Text(
        description,
        modifier = Modifier.padding(top = 7.dp),
        color = Color(0xFF655F69),
        style = MaterialTheme.typography.bodyLarge,
    )
    Spacer(Modifier.height(22.dp))
}

@Composable
private fun SelectionLabel(text: String) {
    Text(
        text,
        modifier = Modifier.padding(top = 12.dp, bottom = 7.dp),
        style = MaterialTheme.typography.titleSmall,
        fontWeight = FontWeight.Bold,
    )
}

private val roleOptions =
    listOf(
        "Androidエンジニア",
        "iOSエンジニア",
        "Webエンジニア",
        "バックエンド",
        "インフラ/SRE",
        "MLエンジニア",
        "デザイナー",
        "PM",
    )

private val interestOptions =
    listOf(
        "モバイル",
        "Web",
        "バックエンド",
        "AI",
        "クラウド",
        "データ",
        "セキュリティ",
        "OSS",
        "DevOps",
        "スタートアップ",
    )

private val regionOptions = listOf("東京", "日本", "アジア", "北米", "欧州", "グローバル", "指定なし")

private val starterTopics =
    listOf(
        "Kotlin",
        "Android",
        "Jetpack Compose",
        "Swift",
        "Flutter",
        "TypeScript",
        "React",
        "Next.js",
        "Node.js",
        "Python",
        "FastAPI",
        "Django",
        "Go",
        "Rust",
        "PostgreSQL",
        "Redis",
        "Docker",
        "Kubernetes",
        "Terraform",
        "AWS",
        "Google Cloud",
        "Cloudflare Workers",
        "GitHub Actions",
        "OpenAI API",
        "Anthropic API",
        "OpenTelemetry",
        "Sentry",
        "Firebase",
        "Supabase",
        "Stripe",
    )
