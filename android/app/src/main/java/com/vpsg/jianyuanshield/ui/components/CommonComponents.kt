package com.vpsg.jianyuanshield.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.GppBad
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.ui.foundation.AnimatedCheckmark
import com.vpsg.jianyuanshield.ui.foundation.GovEmptyArt
import com.vpsg.jianyuanshield.ui.foundation.GradientButton
import com.vpsg.jianyuanshield.ui.foundation.PulseLoader
import com.vpsg.jianyuanshield.ui.foundation.glass
import com.vpsg.jianyuanshield.ui.foundation.pressable
import com.vpsg.jianyuanshield.ui.theme.ElectricBlue
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.PillBg
import com.vpsg.jianyuanshield.ui.theme.PillBorder
import com.vpsg.jianyuanshield.ui.theme.TextHi
import com.vpsg.jianyuanshield.ui.theme.TextMid

/** Frosted glass content card — the primary surface of the Obsidian Aurora UI. */
@Composable
fun SectionCard(
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(18.dp),
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .glass(RoundedCornerShape(14.dp))
            .padding(contentPadding),
        content = content,
    )
}

/** Section title with a neon accent tick, optional subtitle and trailing slot. */
@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .width(4.dp)
                .height(20.dp)
                .background(ElectricBlue, RoundedCornerShape(2.dp)),
        )
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleLarge, color = TextHi)
            if (subtitle != null) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextMid,
                )
            }
        }
        if (trailing != null) trailing()
    }
}

/** Small rounded status pill with a glowing dot. */
@Composable
fun StatusPill(
    text: String,
    tone: StatusTone,
    modifier: Modifier = Modifier,
) {
    val c = tone.colors()
    // 克制统一式:中性极浅底 + hairline 描边 + 小彩点(仅圆点带语义)+ Ink 文字。
    // 无论成功/警告/通过,外观一致庄重——消灭多色糖果撞色。
    Row(
        modifier = modifier
            .background(PillBg, CircleShape)
            .border(1.dp, PillBorder, CircleShape)
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(7.dp)
                .background(c.accent, CircleShape),
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            color = Ink,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
        )
    }
}

/** Translucent white pill for use ON the navy hero banner (white text). */
@Composable
fun GlassPill(text: String, modifier: Modifier = Modifier, dotColor: Color? = null) {
    Row(
        modifier = modifier
            .background(Color.White.copy(alpha = 0.18f), CircleShape)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (dotColor != null) {
            Box(
                Modifier
                    .size(7.dp)
                    .background(dotColor, CircleShape),
            )
            Spacer(Modifier.width(6.dp))
        }
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            color = Color.White,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/** Tinted-glass verdict banner; success verdicts draw their checkmark live. */
@Composable
fun VerdictBanner(
    title: String,
    subtitle: String,
    tone: StatusTone,
    modifier: Modifier = Modifier,
) {
    val c = tone.colors()
    val shape = RoundedCornerShape(14.dp)
    // 干净的语义横幅:实底浅色容器 + hairline,去发光径向/竖向渐变。
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(c.container, shape)
            .border(1.dp, c.accent.copy(alpha = 0.30f), shape)
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(46.dp)
                .background(c.accent.copy(alpha = 0.14f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            when (tone) {
                StatusTone.Success -> AnimatedCheckmark(color = c.accent)
                StatusTone.Warning -> Icon(Icons.Rounded.Warning, null, tint = c.accent)
                StatusTone.Danger -> Icon(Icons.Rounded.GppBad, null, tint = c.accent)
                else -> Icon(Icons.Rounded.Info, null, tint = c.accent)
            }
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                color = TextHi,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = TextMid,
            )
        }
    }
}

/** A single key/value row; pass mono=true for hashes and identifiers. */
@Composable
fun KeyValueRow(
    key: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: Color = TextHi,
    mono: Boolean = false,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            key,
            style = MaterialTheme.typography.bodyMedium,
            color = TextMid,
            modifier = Modifier.weight(1f),
        )
        Spacer(Modifier.width(12.dp))
        Text(
            value,
            style = MaterialTheme.typography.bodyLarge,
            color = valueColor,
            fontWeight = FontWeight.SemiBold,
            fontFamily = if (mono) FontFamily.Monospace else null,
            textAlign = TextAlign.End,
        )
    }
}

// ── Full-screen / inline states ───────────────────────────────────────────────

@Composable
fun LoadingState(
    text: String = "正在加载…",
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        PulseLoader(text = text)
    }
}

@Composable
fun ErrorState(
    message: String,
    onRetry: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier
                .size(56.dp)
                .background(
                    MaterialTheme.colorScheme.error.copy(alpha = 0.12f),
                    CircleShape,
                ),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Rounded.ErrorOutline,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
                modifier = Modifier.size(32.dp),
            )
        }
        Spacer(Modifier.height(12.dp))
        Text(
            message,
            style = MaterialTheme.typography.bodyMedium,
            color = TextMid,
            textAlign = TextAlign.Center,
        )
        if (onRetry != null) {
            Spacer(Modifier.height(18.dp))
            GradientButton(
                text = "重试",
                onClick = onRetry,
                icon = Icons.Rounded.Refresh,
                modifier = Modifier.width(170.dp),
            )
        }
    }
}

@Composable
fun EmptyState(
    text: String = "暂无数据",
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        GovEmptyArt(size = 124.dp)
        Spacer(Modifier.height(16.dp))
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = TextMid,
            textAlign = TextAlign.Center,
        )
    }
}

/** Glass secondary action button. */
@Composable
fun SecondaryButton(
    text: String,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val shape = RoundedCornerShape(14.dp)
    Row(
        modifier = modifier
            .height(48.dp)
            .glass(shape)
            .pressable(onClick = onClick, enabled = enabled)
            .padding(horizontal = 18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        val tint = if (enabled) TextHi else TextHi.copy(alpha = 0.4f)
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(
            text,
            style = MaterialTheme.typography.labelLarge,
            color = tint,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
        )
    }
}
