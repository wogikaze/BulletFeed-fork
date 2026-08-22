package com.bulletfeed.app

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
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

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun TopicsScreen(
    topics: List<String>,
    githubConnected: Boolean,
    onGithubClick: () -> Unit,
    onAddTopic: (String) -> Unit,
    onRemoveTopic: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Scaffold(topBar = { TopAppBar(title = { Text("テーマ") }) }) { padding ->
        LazyColumn(modifier = modifier.padding(padding).fillMaxSize().padding(20.dp)) {
            item {
                Text("追跡中のテーマ", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text("このテーマに起きた変化を優先して届けます。", color = Color(0xFF655F69))
                Spacer(Modifier.height(16.dp))

                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    DemoData.defaultTopics.forEach { topic ->
                        val isSelected = topic in topics
                        FilterChip(
                            selected = isSelected,
                            onClick = {
                                if (isSelected) onRemoveTopic(topic) else onAddTopic(topic)
                            },
                            label = { Text(topic) },
                            leadingIcon =
                                if (isSelected) {
                                    (
                                        {
                                            Icon(Icons.Default.Check, null, Modifier.size(16.dp))
                                        }
                                    )
                                } else {
                                    null
                                },
                            modifier = Modifier.padding(bottom = 8.dp),
                        )
                    }
                }

                Spacer(Modifier.height(24.dp))
                Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFE8F3F1)), shape = RoundedCornerShape(20.dp)) {
                    Column(Modifier.padding(18.dp)) {
                        Text("GitHub連携", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text(
                            if (githubConnected) "2つのリポジトリを監視中\n使用している技術の変更を直接影響として表示します。" else "使っている技術を読み取り、あなたに関係する変更をより正確に届けます。",
                            modifier = Modifier.padding(top = 6.dp),
                            color = Color(0xFF3D5A56),
                        )
                        Spacer(Modifier.height(12.dp))
                        Button(onClick = onGithubClick, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF006A67))) {
                            Text(if (githubConnected) "連携設定を見る" else "GitHubを連携する")
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GithubConnectionScreen(
    connected: Boolean,
    onBack: () -> Unit,
    onConnect: () -> Unit,
    onImportRepo: (String) -> Unit,
) {
    var repoInput by rememberSaveable { mutableStateOf("") }
    var selectedRepositories by remember { mutableStateOf(setOf("bulletfeed-app", "worker-api")) }
    val repositories =
        listOf(
            "bulletfeed-app" to "Kotlin · Jetpack Compose",
            "worker-api" to "TypeScript · Cloudflare Workers",
            "experiments" to "Python · OpenAI API",
        )
    Scaffold(topBar = {
        TopAppBar(title = {
            Text("GitHub連携")
        }, navigationIcon = {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "戻る")
            }
        })
    }) { padding ->
        LazyColumn(Modifier.padding(padding).fillMaxSize().padding(20.dp)) {
            item {
                Box(
                    Modifier.size(54.dp).clip(RoundedCornerShape(16.dp)).background(Color(0xFF24292F)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("GH", color = Color.White, fontWeight = FontWeight.Bold)
                }
                Spacer(Modifier.height(16.dp))
                Text(
                    if (connected) "GitHubを連携済みです" else "GitHubを連携する",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "選択したリポジトリの使用技術や依存関係を、関連性の判定に利用します。ソースコード本文は表示・保存しません。",
                    modifier = Modifier.padding(top = 8.dp),
                    color = Color(0xFF49454F),
                )
                Spacer(Modifier.height(22.dp))
            }
            if (!connected) {
                item {
                    InfoBlock("必要な権限", "公開プロフィールと、あなたが選んだリポジトリのメタデータ・依存関係ファイルの参照")
                    Spacer(Modifier.height(16.dp))
                    Button(
                        onClick = onConnect,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF24292F)),
                    ) {
                        Text("GitHubで認可する")
                    }
                    Text(
                        "デモでは連携状態だけを切り替えます。実運用時はGitHubの認可画面を開きます。",
                        style = MaterialTheme.typography.labelMedium,
                        color = Color(0xFF655F69),
                        modifier = Modifier.padding(top = 10.dp),
                    )
                    Spacer(Modifier.height(24.dp))
                    Text(
                        "または、public repoを指定して技術を取り込む",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = repoInput,
                        onValueChange = { repoInput = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("owner/repo") },
                        singleLine = true,
                    )
                    Spacer(Modifier.height(8.dp))
                    Button(
                        onClick = {
                            if (repoInput.isNotBlank()) {
                                onImportRepo(repoInput)
                                repoInput = ""
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = repoInput.isNotBlank(),
                    ) {
                        Text("技術・ライブラリを取り込む")
                    }
                }
            } else {
                item {
                    Text("監視するリポジトリ", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text("niyu として連携中", color = Color(0xFF006A67), modifier = Modifier.padding(vertical = 5.dp))
                }
                items(repositories) { (name, stack) ->
                    Card(
                        modifier =
                            Modifier.fillMaxWidth().padding(vertical = 6.dp).clickable {
                                selectedRepositories =
                                    if (name in
                                        selectedRepositories
                                    ) {
                                        selectedRepositories - name
                                    } else {
                                        selectedRepositories + name
                                    }
                            },
                        shape = RoundedCornerShape(16.dp),
                        colors = CardDefaults.cardColors(containerColor = Color.White),
                    ) {
                        Row(Modifier.padding(15.dp), verticalAlignment = Alignment.CenterVertically) {
                            Box(
                                Modifier.size(22.dp).clip(RoundedCornerShape(6.dp)).background(
                                    if (name in
                                        selectedRepositories
                                    ) {
                                        Color(0xFF006A67)
                                    } else {
                                        Color(0xFFE0DCE3)
                                    },
                                ),
                                contentAlignment = Alignment.Center,
                            ) {
                                if (name in
                                    selectedRepositories
                                ) {
                                    Icon(
                                        Icons.Default.Check,
                                        contentDescription = "選択済み",
                                        tint = Color.White,
                                        modifier = Modifier.size(18.dp),
                                    )
                                }
                            }
                            Spacer(Modifier.width(12.dp))
                            Column {
                                Text(name, fontWeight = FontWeight.Bold)
                                Text(stack, color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                item {
                    Spacer(Modifier.height(16.dp))
                    Button(onClick = onBack, modifier = Modifier.fillMaxWidth()) { Text("選択を保存") }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    profile: UserProfile,
    modifier: Modifier = Modifier,
) {
    Scaffold(topBar = { TopAppBar(title = { Text("設定") }) }) { padding ->
        Column(modifier.padding(padding).padding(20.dp)) {
            Text("あなたの情報", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(16.dp))
            InfoBlock("職種", profile.role)
            Spacer(Modifier.height(8.dp))
            InfoBlock("興味", profile.interests.joinToString(" · "))
            Spacer(Modifier.height(8.dp))
            InfoBlock("地域", profile.region)
            Spacer(Modifier.height(20.dp))
            OutlinedButton(onClick = {}, modifier = Modifier.fillMaxWidth()) { Text("プロフィールを編集") }
        }
    }
}
