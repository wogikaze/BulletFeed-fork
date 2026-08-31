package com.bulletfeed.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonColors
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp

@Composable
internal fun PoliteEmptyStatus(
    text: String,
    modifier: Modifier = Modifier,
) {
    Text(
        text,
        modifier = modifier.semantics { liveRegion = LiveRegionMode.Polite },
        color = Color(0xFF655F69),
    )
}

@Composable
internal fun AccessibleFilterChip(
    selected: Boolean,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    leadingIcon: @Composable (() -> Unit)? = null,
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        modifier = modifier.defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp),
        label = { Text(label) },
        leadingIcon = leadingIcon,
    )
}

@Composable
internal fun AccessibleAssistChip(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    labelColor: Color = Color.Unspecified,
) {
    AssistChip(
        onClick = onClick,
        modifier = modifier.defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp),
        label = { Text(label) },
        colors = AssistChipDefaults.assistChipColors(labelColor = labelColor),
    )
}

@Composable
internal fun AccessiblePrimaryButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    colors: ButtonColors = ButtonDefaults.buttonColors(),
    content: @Composable RowScope.() -> Unit,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp),
        colors = colors,
        content = content,
    )
}

@Composable
internal fun AccessibleOutlinedButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    content: @Composable RowScope.() -> Unit,
) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp),
        content = content,
    )
}

@Composable
internal fun AccessibleTextButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    content: @Composable RowScope.() -> Unit,
) {
    TextButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp),
        content = content,
    )
}

@Composable
internal fun AccessibleOutlinedTextField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: @Composable (() -> Unit)? = null,
    leadingIcon: @Composable (() -> Unit)? = null,
    singleLine: Boolean = true,
    shape: Shape = OutlinedTextFieldDefaults.shape,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    keyboardActions: KeyboardActions = KeyboardActions.Default,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.defaultMinSize(minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp),
        label = label,
        leadingIcon = leadingIcon,
        singleLine = singleLine,
        shape = shape,
        keyboardOptions = keyboardOptions,
        keyboardActions = keyboardActions,
    )
}

@Composable
internal fun AccessibleIconButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    IconButton(
        onClick = onClick,
        modifier = modifier.defaultMinSize(
            minWidth = AppReadability.MIN_TOUCH_TARGET_DP.dp,
            minHeight = AppReadability.MIN_TOUCH_TARGET_DP.dp,
        ),
        content = content,
    )
}

@Composable
internal fun ReadableTitle(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = Color.Unspecified,
    style: TextStyle = MaterialTheme.typography.titleMedium,
    fontWeight: FontWeight = FontWeight.Bold,
    lineHeight: TextUnit = TextUnit.Unspecified,
) {
    val maxLines = AppReadability.titleMaxLines(LocalDensity.current.fontScale)
    Text(
        text,
        modifier = modifier.testTag("readable-title-max-lines-$maxLines"),
        color = color,
        style = style,
        fontWeight = fontWeight,
        lineHeight = lineHeight,
        maxLines = maxLines,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
internal fun ReadableSummary(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = Color(0xFF49454F),
    style: TextStyle = MaterialTheme.typography.bodyMedium,
) {
    val maxLines = AppReadability.summaryMaxLines(LocalDensity.current.fontScale)
    Text(
        text,
        modifier = modifier.testTag("readable-summary-max-lines-$maxLines"),
        color = color,
        style = style,
        maxLines = maxLines,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
fun AppBarTitle(
    text: String,
    fontWeight: FontWeight = FontWeight.Bold,
) {
    Text(
        text,
        modifier = Modifier.semantics { heading() },
        fontWeight = fontWeight,
    )
}

@Composable
internal fun SectionHeading(
    text: String,
    modifier: Modifier = Modifier,
) {
    Text(
        text,
        modifier = modifier.testTag("section-heading").semantics { heading() },
        style = MaterialTheme.typography.titleLarge,
        fontWeight = FontWeight.Bold,
    )
}

@Composable
fun StatusPill(
    label: String,
    color: Color,
    pale: Boolean = false,
) {
    Text(
        label,
        modifier =
            Modifier
                .clip(
                    RoundedCornerShape(50),
                ).background(if (pale) color.copy(alpha = 0.12f) else color)
                .padding(horizontal = 9.dp, vertical = 4.dp),
        color = if (pale) color else Color.White,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.Bold,
    )
}

@Composable
fun InfoBlock(
    title: String,
    text: String,
) = Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F3F1)), shape = RoundedCornerShape(16.dp)) {
    Column(Modifier.padding(14.dp)) {
        Text(title, color = Color(0xFF655A6D), style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(4.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
fun ChangeBlock(
    label: String,
    text: String,
    color: Color,
) = Column(Modifier.clip(RoundedCornerShape(14.dp)).background(color.copy(alpha = 0.09f)).padding(14.dp)) {
    Text(label, color = color, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelMedium)
    Spacer(Modifier.height(4.dp))
    Text(text, style = MaterialTheme.typography.bodyMedium)
}

@Composable
fun ImpactBlock(
    label: String,
    text: String,
    color: Color,
) = Row(
    Modifier
        .fillMaxWidth()
        .clip(RoundedCornerShape(14.dp))
        .background(color.copy(alpha = 0.08f))
        .padding(14.dp),
    verticalAlignment = Alignment.Top,
) {
    Box(Modifier.size(8.dp).clip(CircleShape).background(color))
    Spacer(Modifier.width(10.dp))
    Column {
        Text(label, color = color, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(4.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
fun TimelineRow(item: TimelineItem) =
    Row(Modifier.padding(top = 12.dp)) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.size(10.dp).clip(CircleShape).background(Color(0xFF1769AA)))
            Box(Modifier.width(2.dp).height(44.dp).background(Color(0xFFD9E3EC)))
        }
        Spacer(Modifier.width(12.dp))
        Column {
            Text(item.date, style = MaterialTheme.typography.labelMedium, color = Color(0xFF655F69))
            Text(item.title, fontWeight = FontWeight.Bold)
            Text(item.description, style = MaterialTheme.typography.bodyMedium, color = Color(0xFF49454F))
        }
    }

@Composable
fun SourceBlock(source: Source) =
    Card(
        modifier = Modifier.padding(top = 8.dp).fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(14.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(source.publisher, color = Color(0xFF1769AA), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
            Text(source.title, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            Text("根拠: ${source.evidence}", style = MaterialTheme.typography.bodySmall, color = Color(0xFF49454F))
        }
    }
