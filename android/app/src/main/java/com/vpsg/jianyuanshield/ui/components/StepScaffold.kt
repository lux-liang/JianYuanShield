package com.vpsg.jianyuanshield.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.ui.foundation.GradientButton
import com.vpsg.jianyuanshield.ui.foundation.OutlineButton
import com.vpsg.jianyuanshield.ui.theme.CardBg
import com.vpsg.jianyuanshield.ui.theme.Divider
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.InkFaint
import com.vpsg.jianyuanshield.ui.theme.InkSecondary

/**
 * Numbered step progress bar: filled navy circles + connecting tracks that fill
 * as the user advances. Calm and official — no neon.
 */
@Composable
fun StepProgress(
    current: Int,        // 1-based
    total: Int,
    labels: List<String> = emptyList(),
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        for (i in 1..total) {
            val done = i <= current
            val circleColor by animateColorAsState(if (done) GovBlue else CardBg, label = "step-c$i")
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Box(
                    Modifier
                        .size(24.dp)
                        .border(1.dp, if (done) GovBlue else Divider, CircleShape)
                        .background(circleColor, CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        "$i",
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = if (done) Color.White else InkFaint,
                    )
                }
                if (labels.isNotEmpty() && i <= labels.size) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        labels[i - 1],
                        style = MaterialTheme.typography.labelSmall,
                        color = if (done) GovBlue else InkSecondary,
                    )
                }
            }
            if (i < total) {
                Box(
                    Modifier
                        .weight(1f)
                        .padding(horizontal = 6.dp)
                        .height(2.dp)
                        .background(if (i < current) GovBlue else Divider),
                )
            }
        }
    }
}

/**
 * Wizard frame: white top bar + step progress + scrollable body + a fixed
 * bottom action row (上一步 outline / 下一步 primary).
 */
@Composable
fun StepScaffold(
    title: String,
    currentStep: Int,
    totalSteps: Int,
    stepLabels: List<String>,
    primaryText: String,
    onPrimary: () -> Unit,
    onBack: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
    primaryEnabled: Boolean = true,
    secondaryText: String? = null,
    onSecondary: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(modifier.fillMaxSize()) {
        GradientTopBar(title = title, onBack = onBack)

        Box(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 32.dp, vertical = 16.dp),
        ) {
            StepProgress(currentStep, totalSteps, stepLabels)
        }

        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
            content = content,
        )

        // Fixed bottom action bar — raised clear of the floating bottom dock.
        Row(
            Modifier
                .fillMaxWidth()
                .background(CardBg)
                .navigationBarsPadding()
                .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 74.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (secondaryText != null && onSecondary != null) {
                OutlineButton(
                    text = secondaryText,
                    onClick = onSecondary,
                    modifier = Modifier.weight(1f),
                )
            }
            GradientButton(
                text = primaryText,
                onClick = onPrimary,
                enabled = primaryEnabled,
                modifier = Modifier.weight(if (secondaryText != null) 1.6f else 1f),
            )
        }
    }
}
