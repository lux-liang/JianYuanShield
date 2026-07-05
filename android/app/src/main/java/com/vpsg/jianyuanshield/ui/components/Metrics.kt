package com.vpsg.jianyuanshield.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.core.MetricRow
import com.vpsg.jianyuanshield.ui.theme.ElectricBlue
import com.vpsg.jianyuanshield.ui.theme.NeonCyan
import com.vpsg.jianyuanshield.ui.theme.TextMid

/** Two-column responsive grid of metric tiles. */
@Composable
fun MetricGrid(
    rows: List<MetricRow>,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        rows.chunked(2).forEach { pair ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                pair.forEach { row ->
                    MetricTile(row, Modifier.weight(1f))
                }
                if (pair.size == 1) {
                    Spacer(Modifier.weight(1f))
                }
            }
            Spacer(Modifier.height(12.dp))
        }
    }
}

@Composable
private fun MetricTile(row: MetricRow, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .background(MaterialTheme.colorScheme.surfaceContainerHigh, RoundedCornerShape(16.dp))
            .padding(horizontal = 14.dp, vertical = 13.dp),
    ) {
        Box(
            Modifier
                .width(3.dp)
                .height(34.dp)
                .background(
                    Brush.verticalGradient(listOf(ElectricBlue, NeonCyan)),
                    RoundedCornerShape(2.dp),
                ),
        )
        Spacer(Modifier.width(11.dp))
        Column {
            Text(
                row.value,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Black,
                color = com.vpsg.jianyuanshield.ui.theme.GovBlue,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(1.dp))
            Text(
                row.label,
                style = MaterialTheme.typography.labelMedium,
                color = TextMid,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
