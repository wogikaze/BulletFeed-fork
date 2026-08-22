package com.bulletfeed.app

import androidx.compose.ui.graphics.Color

enum class VulnerabilitySeverity(
    val label: String,
    val color: Color,
) {
    CRITICAL("緊急", Color(0xFFB42318)),
    HIGH("重要", Color(0xFFD55A00)),
    MEDIUM("注意", Color(0xFF9A6700)),
    LOW("低", Color(0xFF5F6368)),
}

enum class VulnerabilityStatus(
    val label: String,
) {
    OPEN("未対応"),
    IN_PROGRESS("対応中"),
    RESOLVED("解決済み"),
    NOT_AFFECTED("対象外"),
}

enum class DependencyType(
    val label: String,
) {
    DIRECT("直接依存"),
    TRANSITIVE("間接依存"),
}

enum class SecurityFilter(
    val label: String,
) {
    ACTION_REQUIRED("要対応"),
    IN_PROGRESS("対応中"),
    RESOLVED("解決済み"),
    ALL("すべて"),
}

data class VulnerabilityAlert(
    val id: String,
    val advisoryId: String,
    val cve: String?,
    val title: String,
    val summary: String,
    val severity: VulnerabilitySeverity,
    val status: VulnerabilityStatus,
    val repository: String,
    val packageName: String,
    val currentVersion: String,
    val fixedVersion: String?,
    val dependencyType: DependencyType,
    val detectedAt: String,
    val source: String,
    val evidence: String,
    val recommendation: String,
    val cvssScore: Double?,
)
