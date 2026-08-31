package com.bulletfeed.app

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Security
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SecurityDashboardScreen(
    alerts: List<VulnerabilityAlert>,
    onAlertClick: (VulnerabilityAlert) -> Unit,
    modifier: Modifier = Modifier,
) {
    var filter by remember { mutableStateOf(SecurityFilter.ACTION_REQUIRED) }
    val visibleAlerts = alerts.filter { alert -> filter.matches(alert.status) }
    val actionRequiredCount = alerts.count { it.status == VulnerabilityStatus.OPEN }
    val criticalCount =
        alerts.count {
            it.status == VulnerabilityStatus.OPEN && it.severity == VulnerabilitySeverity.CRITICAL
        }

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { AppBarTitle("セキュリティ") },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFFFFFBF8)),
            )
        },
    ) { padding ->
        LazyColumn(modifier = Modifier.padding(padding).fillMaxSize()) {
            item {
                SecuritySummaryCard(
                    actionRequiredCount = actionRequiredCount,
                    criticalCount = criticalCount,
                )
                Text(
                    "GitHubで利用中の依存関係と公開アドバイザリを照合した結果です。",
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
                    color = Color(0xFF655F69),
                    style = MaterialTheme.typography.bodySmall,
                )
                SecurityFilterRow(
                    selected = filter,
                    alerts = alerts,
                    onSelect = { filter = it },
                )
                Row(
                    modifier = Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    SectionHeading(filter.heading)
                    Spacer(Modifier.weight(1f))
                    Text("${visibleAlerts.size}件", color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
                }
            }
            if (visibleAlerts.isEmpty()) {
                item { SecurityEmptyState(filter) }
            } else {
                items(visibleAlerts, key = { it.id }) { alert ->
                    VulnerabilityCard(alert = alert, onClick = { onAlertClick(alert) })
                }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

private val SecurityFilter.heading: String
    get() =
        when (this) {
            SecurityFilter.ACTION_REQUIRED -> "対応が必要"
            SecurityFilter.IN_PROGRESS -> "対応中"
            SecurityFilter.RESOLVED -> "解決済み"
            SecurityFilter.ALL -> "すべての検出結果"
        }

private fun SecurityFilter.matches(status: VulnerabilityStatus): Boolean =
    when (this) {
        SecurityFilter.ACTION_REQUIRED -> status == VulnerabilityStatus.OPEN
        SecurityFilter.IN_PROGRESS -> status == VulnerabilityStatus.IN_PROGRESS
        SecurityFilter.RESOLVED -> status == VulnerabilityStatus.RESOLVED
        SecurityFilter.ALL -> true
    }

@Composable
private fun SecuritySummaryCard(
    actionRequiredCount: Int,
    criticalCount: Int,
) = Card(
    modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp).fillMaxWidth(),
    colors = CardDefaults.cardColors(containerColor = Color(0xFF9D231C)),
    shape = RoundedCornerShape(24.dp),
) {
    Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier.size(46.dp).clip(CircleShape).background(Color(0xFFC83C32)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.Security, contentDescription = null, tint = Color.White)
        }
        Column(Modifier.padding(start = 13.dp)) {
            Text("対応が必要", color = Color(0xFFFFDAD5), style = MaterialTheme.typography.labelLarge)
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    "$actionRequiredCount",
                    color = Color.White,
                    style = MaterialTheme.typography.headlineLarge,
                    fontWeight = FontWeight.Bold,
                )
                Text("件", modifier = Modifier.padding(start = 3.dp, bottom = 5.dp), color = Color.White)
            }
            if (criticalCount > 0) {
                Text("うち緊急 $criticalCount 件", color = Color(0xFFFFD8A8), style = MaterialTheme.typography.bodySmall)
            }
        }
        Spacer(Modifier.weight(1f))
        Column(horizontalAlignment = Alignment.End) {
            Text("最終確認", color = Color(0xFFFFDAD5), style = MaterialTheme.typography.labelSmall)
            Text("5分前", color = Color.White, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun SecurityFilterRow(
    selected: SecurityFilter,
    alerts: List<VulnerabilityAlert>,
    onSelect: (SecurityFilter) -> Unit,
) = LazyRow(
    contentPadding =
        androidx.compose.foundation.layout
            .PaddingValues(horizontal = 20.dp, vertical = 6.dp),
    horizontalArrangement = Arrangement.spacedBy(8.dp),
) {
    items(SecurityFilter.entries) { filter ->
        val count = alerts.count { filter.matches(it.status) }
        AccessibleFilterChip(
            selected = selected == filter,
            onClick = { onSelect(filter) },
            label = "${filter.label} $count",
        )
    }
}

@Composable
private fun VulnerabilityCard(
    alert: VulnerabilityAlert,
    onClick: () -> Unit,
) = Card(
    modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp).fillMaxWidth().clickable(onClick = onClick),
    shape = RoundedCornerShape(20.dp),
    colors = CardDefaults.cardColors(containerColor = Color.White),
    elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
) {
    Column(Modifier.padding(16.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            StatusPill(alert.severity.label, alert.severity.color)
            VulnerabilityStatusPill(alert.status)
            Spacer(Modifier.weight(1f))
            alert.cvssScore?.let { score ->
                Text("CVSS $score", color = alert.severity.color, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.height(11.dp))
        ReadableTitle(alert.title)
        ReadableSummary(
            alert.summary,
            modifier = Modifier.padding(top = 6.dp),
        )
        Spacer(Modifier.height(12.dp))
        Row(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(alert.severity.color.copy(alpha = 0.08f))
                    .padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(alert.repository, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelLarge)
                Text(
                    "${alert.packageName} ${alert.currentVersion} · ${alert.dependencyType.label}",
                    color = Color(0xFF655F69),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = "詳細を見る", tint = alert.severity.color)
        }
        Spacer(Modifier.height(10.dp))
        HorizontalDivider(color = Color(0xFFEAE5EC))
        Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(alert.advisoryId, color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.weight(1f))
            Text(alert.detectedAt, color = Color(0xFF655F69), style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
private fun VulnerabilityStatusPill(status: VulnerabilityStatus) {
    val color =
        when (status) {
            VulnerabilityStatus.OPEN -> Color(0xFFB42318)
            VulnerabilityStatus.IN_PROGRESS -> Color(0xFF9A6700)
            VulnerabilityStatus.RESOLVED -> Color(0xFF006A67)
            VulnerabilityStatus.NOT_AFFECTED -> Color(0xFF5F6368)
        }
    StatusPill(status.label, color, pale = true)
}

@Composable
internal fun SecurityEmptyState(filter: SecurityFilter) =
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(40.dp)
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(Icons.Default.Security, contentDescription = null, tint = Color(0xFF006A67), modifier = Modifier.size(42.dp))
        Spacer(Modifier.height(10.dp))
        Text("${filter.label}の項目はありません", fontWeight = FontWeight.Bold)
        Text("新しい検出結果が届くとここに表示されます。", color = Color(0xFF655F69), style = MaterialTheme.typography.bodySmall)
    }
