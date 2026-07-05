package com.vpsg.jianyuanshield.ui.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.FactCheck
import androidx.compose.material.icons.outlined.Fingerprint
import androidx.compose.material.icons.outlined.Gavel
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material.icons.automirrored.rounded.FactCheck
import androidx.compose.material.icons.rounded.Fingerprint
import androidx.compose.material.icons.rounded.Gavel
import androidx.compose.material.icons.rounded.Home
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.ui.graphics.vector.ImageVector

object Routes {
    const val HOME = "home"
    const val INFER = "infer"
    const val COMPLIANCE = "compliance"
    const val EVIDENCE = "evidence"
    const val SETTINGS = "settings"
    const val BENCHMARK = "benchmark"
    const val EVAL_REPORT = "eval_report"
    const val ABOUT = "about"
}

data class BottomItem(
    val route: String,
    val label: String,
    val selectedIcon: ImageVector,
    val unselectedIcon: ImageVector,
)

val BottomItems: List<BottomItem> = listOf(
    BottomItem(Routes.HOME, "首页", Icons.Rounded.Home, Icons.Outlined.Home),
    BottomItem(Routes.INFER, "溯源", Icons.Rounded.Fingerprint, Icons.Outlined.Fingerprint),
    BottomItem(Routes.COMPLIANCE, "合规", Icons.AutoMirrored.Rounded.FactCheck, Icons.AutoMirrored.Outlined.FactCheck),
    BottomItem(Routes.EVIDENCE, "证据链", Icons.Rounded.Gavel, Icons.Outlined.Gavel),
    BottomItem(Routes.SETTINGS, "设置", Icons.Rounded.Tune, Icons.Outlined.Tune),
)
