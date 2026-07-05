package com.vpsg.jianyuanshield.ui.foundation

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.ui.theme.CardBg
import com.vpsg.jianyuanshield.ui.theme.Divider
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.GovBluePressed
import com.vpsg.jianyuanshield.ui.theme.InkFaint
import com.vpsg.jianyuanshield.ui.theme.ShadowCard
import com.vpsg.jianyuanshield.ui.theme.ShadowSoft
import com.vpsg.jianyuanshield.ui.theme.ShadowStrong

/**
 * Government white card: flat white surface, very soft low-opacity shadow,
 * hairline border, large radius. (Name kept as `glass` for call-site stability;
 * the GovTrust language is matte, NOT glassmorphism.)
 */
fun Modifier.glass(
    shape: Shape,
    strong: Boolean = false,
): Modifier = this
    .shadow(
        elevation = if (strong) 6.dp else 3.dp,   // 更轻的阴影,靠清晰 hairline 立卡
        shape = shape,
        ambientColor = ShadowCard,
        spotColor = if (strong) ShadowStrong else ShadowCard,
    )
    .background(CardBg, shape)
    .border(1.dp, Divider, shape)

/**
 * Primary action button: solid navy, white bold text, 12dp radius, 52dp tall.
 * Disabled = muted gray fill (never a dead slab — still legible).
 */
@Composable
fun GradientButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    loading: Boolean = false,
) {
    val shape = RoundedCornerShape(10.dp)
    val filled = enabled
    val clickable = enabled && !loading
    val fg = if (filled) Color.White else InkFaint
    Box(
        modifier = modifier
            .height(52.dp)
            .shadow(
                elevation = if (filled) 6.dp else 0.dp,
                shape = shape,
                ambientColor = ShadowStrong,
                spotColor = ShadowStrong,
            )
            .background(if (filled) GovBlue else Color(0xFFE6E9F0), shape)
            .pressable(onClick = onClick, enabled = clickable),
        contentAlignment = Alignment.Center,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (loading) {
                CircularProgressIndicator(
                    strokeWidth = 2.dp,
                    color = fg,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(10.dp))
            } else if (icon != null) {
                Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
            }
            Text(
                text,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = fg,
            )
        }
    }
}

/** Full-width convenience overload used by form screens. */
@Composable
fun GradientButtonWide(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    loading: Boolean = false,
) = GradientButton(text, onClick, modifier.fillMaxWidth(), icon, enabled, loading)

/** Secondary action: white pill, navy outline + navy text. */
@Composable
fun OutlineButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val shape = RoundedCornerShape(10.dp)
    Box(
        modifier = modifier
            .height(52.dp)
            .shadow(elevation = 4.dp, shape = shape, ambientColor = ShadowSoft, spotColor = ShadowSoft)
            .background(CardBg, shape)
            .border(1.5.dp, if (enabled) GovBlue else InkFaint, shape)
            .pressable(onClick = onClick, enabled = enabled),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = if (enabled) GovBlue else InkFaint,
        )
    }
}

// Keep a referenceable pressed color (used by some call sites/theming).
internal val PrimaryPressed = GovBluePressed
