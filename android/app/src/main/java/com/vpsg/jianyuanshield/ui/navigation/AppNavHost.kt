package com.vpsg.jianyuanshield.ui.navigation

import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.vpsg.jianyuanshield.ui.foundation.AuroraBackground
import com.vpsg.jianyuanshield.ui.foundation.LuxEase
import com.vpsg.jianyuanshield.ui.foundation.pressable
import com.vpsg.jianyuanshield.ui.screens.about.AboutScreen
import com.vpsg.jianyuanshield.ui.screens.benchmark.BenchmarkScreen
import com.vpsg.jianyuanshield.ui.screens.compliance.ComplianceScreen
import com.vpsg.jianyuanshield.ui.screens.evidence.EvalReportScreen
import com.vpsg.jianyuanshield.ui.screens.evidence.EvidenceScreen
import com.vpsg.jianyuanshield.ui.screens.home.HomeScreen
import com.vpsg.jianyuanshield.ui.screens.infer.InferScreen
import com.vpsg.jianyuanshield.ui.screens.settings.SettingsScreen
import com.vpsg.jianyuanshield.ui.theme.CardBg
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.GovBlueTint
import com.vpsg.jianyuanshield.ui.theme.InkSecondary

@Composable
fun AppNavHost() {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val showBottomBar = BottomItems.any { it.route == currentRoute }

    Box(Modifier.fillMaxSize()) {
        AuroraBackground(Modifier.fillMaxSize())

        Scaffold(
            containerColor = Color.Transparent,
            bottomBar = {
                if (showBottomBar) {
                    GovDock(
                        currentRoute = currentRoute,
                        onSelect = { navController.navigateTopLevel(it) },
                    )
                }
            },
        ) { innerPadding ->
            NavHost(
                navController = navController,
                startDestination = Routes.HOME,
                modifier = Modifier.padding(innerPadding),
                enterTransition = { fadeIn(tween(220)) },
                exitTransition = { fadeOut(tween(120)) },
                popEnterTransition = { fadeIn(tween(220)) },
                popExitTransition = { fadeOut(tween(120)) },
            ) {
                composable(Routes.HOME) {
                    HomeScreen(
                        onNavigate = { route ->
                            if (BottomItems.any { it.route == route }) {
                                navController.navigateTopLevel(route)
                            } else {
                                navController.navigate(route)
                            }
                        },
                    )
                }
                composable(Routes.INFER) { InferScreen() }
                composable(Routes.COMPLIANCE) { ComplianceScreen() }
                composable(Routes.EVIDENCE) {
                    EvidenceScreen(onOpenReport = { navController.navigate(Routes.EVAL_REPORT) })
                }
                composable(Routes.SETTINGS) {
                    SettingsScreen(onOpenAbout = { navController.navigate(Routes.ABOUT) })
                }
                composable(Routes.BENCHMARK) {
                    BenchmarkScreen(onBack = { navController.popBackStack() })
                }
                composable(Routes.EVAL_REPORT) {
                    EvalReportScreen(onBack = { navController.popBackStack() })
                }
                composable(Routes.ABOUT) {
                    AboutScreen(onBack = { navController.popBackStack() })
                }
            }
        }
    }
}

/** White government dock: navy selected tab with a short underline indicator. */
@Composable
private fun GovDock(currentRoute: String?, onSelect: (String) -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            // Soft upward shadow + rounded top = the "simple yet detailed" bar.
            .shadow(
                elevation = 16.dp,
                shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp),
                ambientColor = Color(0x1A0B3A8D),
                spotColor = Color(0x1A0B3A8D),
            )
            .background(CardBg, RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp)),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .height(62.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BottomItems.forEach { item ->
                DockItem(
                    item = item,
                    selected = currentRoute == item.route,
                    onClick = { onSelect(item.route) },
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun DockItem(
    item: BottomItem,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val scale by animateFloatAsState(
        targetValue = if (selected) 1.05f else 1f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMediumLow),
        label = "dock-scale",
    )
    val tint = if (selected) GovBlue else InkSecondary
    Column(
        modifier = modifier
            .fillMaxSize()
            .pressable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = androidx.compose.foundation.layout.Arrangement.Center,
    ) {
        Box(
            Modifier.size(30.dp).scale(scale),
            contentAlignment = Alignment.Center,
        ) {
            if (selected) {
                Box(Modifier.size(30.dp).background(GovBlueTint, CircleShape))
            }
            Icon(
                if (selected) item.selectedIcon else item.unselectedIcon,
                contentDescription = item.label,
                tint = tint,
                modifier = Modifier.size(22.dp),
            )
        }
        Spacer(Modifier.height(3.dp))
        Text(
            item.label,
            style = androidx.compose.material3.MaterialTheme.typography.labelSmall,
            color = tint,
        )
        Spacer(Modifier.height(3.dp))
        Box(
            Modifier
                .size(width = if (selected) 16.dp else 0.dp, height = 2.dp)
                .background(if (selected) GovBlue else Color.Transparent, RoundedCornerShape(1.dp)),
        )
    }
}

private fun NavController.navigateTopLevel(route: String) {
    navigate(route) {
        popUpTo(graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
