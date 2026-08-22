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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
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
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun OnboardingScreen(
    initialProfile: UserProfile,
    initialTopics: List<String>,
    isSaving: Boolean,
    onComplete: (UserProfile, List<String>, Boolean) -> Unit,
) {
    var step by rememberSaveable { mutableIntStateOf(0) }
    var role by rememberSaveable { mutableStateOf(initialProfile.role.ifBlank { "Androidエンジニア" }) }
    var interests by remember { mutableStateOf(initialProfile.interests.ifEmpty { setOf("モバイル", "AI", "クラウド") }) }
    var region by rememberSaveable { mutableStateOf(initialProfile.region.ifBlank { "東京" }) }
    var topics by remember { mutableStateOf(initialTopics.ifEmpty { DemoData.defaultTopics.take(DemoData.MINIMUM_TOPIC_COUNT) }) }
    var connectGithub by rememberSaveable { mutableStateOf(true) }

    val canContinue =
        when (step) {
            0 -> role.isNotBlank() && interests.isNotEmpty()
            1 -> topics.size >= DemoData.MINIMUM_TOPIC_COUNT
            else -> true
        }

    BackHandler(enabled = step > 0) { step -= 1 }
    Scaffold(
        topBar = {
            OnboardingHeader(step = step)
        },
        bottomBar = {
            OnboardingActions(
                step = step,
                canContinue = canContinue,
                isSaving = isSaving,
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
                androidx.compose.foundation.layout
                    .PaddingValues(horizontal = 20.dp, vertical = 14.dp),
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
                                interests = if (interest in interests) interests - interest else interests + interest
                            },
                            onRegionChange = { region = it },
                        )
                    1 ->
                        TopicsStep(
                            topics = topics,
                            onToggle = { topic ->
                                topics = if (topic in topics) topics - topic else topics + topic
                            },
                        )
                    else ->
                        GithubStep(
                            connectGithub = connectGithub,
                            onSelectionChange = { connectGithub = it },
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
    onBack: () -> Unit,
    onNext: () -> Unit,
) = Surface(tonalElevation = 3.dp, color = Color.White) {
    Row(
        modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 10.dp),
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
                CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = Color.White)
            } else {
                Text(if (step == 2) "BulletFeedを始める" else "次へ")
                Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null, modifier = Modifier.padding(start = 6.dp).size(18.dp))
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
        description = "職種や興味から、変化が自分に関係する理由を判断します。",
    )
    SelectionLabel("職種")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        roleOptions.forEach { option ->
            FilterChip(selected = role == option, onClick = { onRoleChange(option) }, label = { Text(option) })
        }
    }
    SelectionLabel("興味のある分野")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        interestOptions.forEach { option ->
            FilterChip(
                selected = option in interests,
                onClick = { onInterestToggle(option) },
                label = { Text(option) },
                leadingIcon = if (option in interests) ({ Icon(Icons.Default.Check, null, Modifier.size(16.dp)) }) else null,
            )
        }
    }
    SelectionLabel("地域（任意）")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        regionOptions.forEach { option ->
            FilterChip(selected = region == option, onClick = { onRegionChange(option) }, label = { Text(option) })
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TopicsStep(
    topics: List<String>,
    onToggle: (String) -> Unit,
) {
    StepTitle(
        icon = { Icon(Icons.Default.Topic, contentDescription = null, tint = Color.White) },
        title = "追いかけるテーマを選択",
        description = "技術・サービス・企業を5件以上選んでください。あとから変更できます。",
    )
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors =
            CardDefaults.cardColors(
                containerColor = if (topics.size >= DemoData.MINIMUM_TOPIC_COUNT) Color(0xFFE8F3F1) else Color(0xFFFFF1D8),
            ),
        shape = RoundedCornerShape(16.dp),
    ) {
        Text(
            if (topics.size >= DemoData.MINIMUM_TOPIC_COUNT) "${topics.size}件を追跡します" else "あと${DemoData.MINIMUM_TOPIC_COUNT - topics.size}件選択してください",
            modifier = Modifier.padding(14.dp),
            color = if (topics.size >= DemoData.MINIMUM_TOPIC_COUNT) Color(0xFF006A67) else Color(0xFF8A5A00),
            fontWeight = FontWeight.Bold,
        )
    }
    SelectionLabel("おすすめ")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        DemoData.defaultTopics.forEach { topic ->
            FilterChip(
                selected = topic in topics,
                onClick = { onToggle(topic) },
                label = { Text(topic) },
                leadingIcon = if (topic in topics) ({ Icon(Icons.Default.Check, null, Modifier.size(16.dp)) }) else null,
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
        title = "GitHubから影響を見つける",
        description = "利用技術と依存関係を読み取り、自分への直接影響や脆弱性を見つけやすくします。",
    )
    GithubChoiceCard(
        selected = connectGithub,
        title = "GitHubを連携する",
        description = "選んだリポジトリのメタデータと依存関係だけを利用します。",
        onClick = { onSelectionChange(true) },
    )
    Spacer(Modifier.height(10.dp))
    GithubChoiceCard(
        selected = !connectGithub,
        title = "あとで連携する",
        description = "テーマとプロフィールだけでフィードを開始します。",
        onClick = { onSelectionChange(false) },
    )
    Spacer(Modifier.height(18.dp))
    Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F3F1)), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(16.dp)) {
            Text("安全な連携方法", fontWeight = FontWeight.Bold)
            HorizontalDivider(Modifier.padding(vertical = 10.dp), color = Color(0xFFE0D8D4))
            Text(
                "本番環境では認可トークンをバックエンドだけで保管します。ソースコード本文は保存せず、連携するリポジトリも自分で選べます。",
                color = Color(0xFF655F69),
                style = MaterialTheme.typography.bodyMedium,
            )
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
    border = androidx.compose.foundation.BorderStroke(2.dp, if (selected) Color(0xFF006A67) else Color(0xFFE0D8D4)),
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
            if (selected) Icon(Icons.Default.Check, contentDescription = "選択済み", tint = Color.White, modifier = Modifier.size(19.dp))
        }
        Column(Modifier.padding(start = 12.dp)) {
            Text(title, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
            Text(description, modifier = Modifier.padding(top = 4.dp), color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
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
        modifier = Modifier.size(50.dp).clip(RoundedCornerShape(16.dp)).background(Color(0xFFA6231C)),
        contentAlignment = Alignment.Center,
    ) {
        icon()
    }
    Spacer(Modifier.height(14.dp))
    Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    Text(description, modifier = Modifier.padding(top = 7.dp), color = Color(0xFF655F69), style = MaterialTheme.typography.bodyLarge)
    Spacer(Modifier.height(22.dp))
}

@Composable
private fun SelectionLabel(text: String) {
    Text(text, modifier = Modifier.padding(top = 12.dp, bottom = 7.dp), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
}

private val roleOptions = listOf("Androidエンジニア", "Webエンジニア", "バックエンド", "デザイナー", "PM")
private val interestOptions = listOf("モバイル", "AI", "クラウド", "セキュリティ", "OSS", "スタートアップ")
private val regionOptions = listOf("東京", "日本", "グローバル", "指定なし")
