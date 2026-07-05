package com.vpsg.jianyuanshield.ui.pub

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.vpsg.jianyuanshield.ui.pub.screens.PubCertificateScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubConfirmScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubDetectingScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubHomeScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubLearnScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubMeScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubOnboardingScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubRecordsScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubArticleScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubInfoScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubReportScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubResultScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubServerScreen
import com.vpsg.jianyuanshield.ui.pub.screens.PubUploadScreen

/** 公众版路由表。 */
object PubRoutes {
    const val ONBOARDING = "onboarding"
    const val HOME = "home"
    const val UPLOAD = "upload"
    const val CONFIRM = "confirm"
    const val DETECTING = "detecting"
    const val RESULT = "result"
    const val REPORT = "report"
    const val CERTIFICATE = "certificate"
    const val RECORDS = "records"
    const val ME = "me"
    const val LEARN = "learn"
    const val SETTINGS = "settings"
    const val INFO = "info/{key}"
    const val ARTICLE = "article/{index}"

    fun info(key: String) = "info/$key"
    fun article(index: Int) = "article/$index"
}

/** 底部 Tab 切换:回到对应主路由,清理中间栈,避免重复入栈。 */
private fun NavHostController.switchTab(tab: PubTab) {
    val route = when (tab) {
        PubTab.Home -> PubRoutes.HOME
        PubTab.Detect -> PubRoutes.UPLOAD
        PubTab.Records -> PubRoutes.RECORDS
        PubTab.Me -> PubRoutes.ME
    }
    navigate(route) {
        popUpTo(PubRoutes.HOME) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}

@Composable
fun PubApp(
    nav: NavHostController = rememberNavController(),
    // 整条鉴别流程共享的会话 VM(Activity 作用域,贯穿 上传→…→凭证)。
    vm: PubDetectViewModel = viewModel(factory = PubDetectViewModel.Factory),
) {
    // ⑤ 大字模式:放大全局字号(sp 本就跟随系统字体大小,这里再叠一档适老化)。
    val bigFont by vm.bigFont.collectAsState()
    val baseDensity = LocalDensity.current
    val density = if (bigFont) Density(baseDensity.density, baseDensity.fontScale * 1.15f) else baseDensity
    CompositionLocalProvider(LocalDensity provides density) {
    NavHost(
        navController = nav,
        startDestination = PubRoutes.ONBOARDING,
        // 进入流程:新页从右侧滑入,旧页向左微移淡出。slide 与 fade 同时长,避免"幽灵滑动"。
        enterTransition = {
            slideInHorizontally(tween(300, easing = FastOutSlowInEasing)) { it / 3 } + fadeIn(tween(300, easing = FastOutSlowInEasing))
        },
        exitTransition = {
            slideOutHorizontally(tween(250, easing = FastOutSlowInEasing)) { -it / 6 } + fadeOut(tween(250))
        },
        // 返回:反方向
        popEnterTransition = {
            slideInHorizontally(tween(300, easing = FastOutSlowInEasing)) { -it / 3 } + fadeIn(tween(300, easing = FastOutSlowInEasing))
        },
        popExitTransition = {
            slideOutHorizontally(tween(250, easing = FastOutSlowInEasing)) { it / 3 } + fadeOut(tween(250))
        },
    ) {
        composable(
            PubRoutes.ONBOARDING,
            exitTransition = { fadeOut(tween(400)) },   // 引导完成 → 首页淡出揭幕
        ) {
            PubOnboardingScreen(onFinish = {
                nav.navigate(PubRoutes.HOME) { popUpTo(PubRoutes.ONBOARDING) { inclusive = true } }
            })
        }
        composable(
            PubRoutes.HOME,
            enterTransition = {
                if (initialState.destination.route == PubRoutes.ONBOARDING) fadeIn(tween(400))
                else fadeIn(tween(220))
            },
            exitTransition = { fadeOut(tween(160)) },
            popEnterTransition = { fadeIn(tween(220)) },
            popExitTransition = { fadeOut(tween(160)) },
        ) {
            PubHomeScreen(
                vm = vm,
                onUpload = { nav.navigate(PubRoutes.UPLOAD) },
                onOpenRecords = { nav.navigate(PubRoutes.RECORDS) },
                onOpenLearn = { nav.navigate(PubRoutes.LEARN) },
                onSelectTab = nav::switchTab,
            )
        }
        composable(
            PubRoutes.UPLOAD,
            enterTransition = { fadeIn(tween(220)) },
            exitTransition = { fadeOut(tween(160)) },
            popEnterTransition = { fadeIn(tween(220)) },
            popExitTransition = { fadeOut(tween(160)) },
        ) {
            PubUploadScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onPicked = { nav.navigate(PubRoutes.CONFIRM) },
                onOpenServer = { nav.navigate(PubRoutes.SETTINGS) },
                onSelectTab = nav::switchTab,
            )
        }
        composable(PubRoutes.CONFIRM) {
            PubConfirmScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onStart = { nav.navigate(PubRoutes.DETECTING) },
                onRepick = { nav.popBackStack() },
                onSelectTab = nav::switchTab,
            )
        }
        composable(PubRoutes.DETECTING) {
            PubDetectingScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onDone = { nav.navigate(PubRoutes.RESULT) { popUpTo(PubRoutes.DETECTING) { inclusive = true } } },
                onSelectTab = nav::switchTab,
            )
        }
        composable(
            PubRoutes.RESULT,
            // 结果揭晓:轻微放大淡入,更有"出结论"的仪式感
            enterTransition = { scaleIn(tween(380, easing = FastOutSlowInEasing), initialScale = 0.92f) + fadeIn(tween(320)) },
            exitTransition = { fadeOut(tween(200)) },
        ) {
            PubResultScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onSaveCertificate = { nav.navigate(PubRoutes.CERTIFICATE) },
                onOpenReport = { nav.navigate(PubRoutes.REPORT) },
                onRetry = {
                    vm.reset()
                    nav.navigate(PubRoutes.UPLOAD) { popUpTo(PubRoutes.HOME) }
                },
                onSelectTab = nav::switchTab,
            )
        }
        composable(PubRoutes.REPORT) {
            PubReportScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onSaveCertificate = { nav.navigate(PubRoutes.CERTIFICATE) },
                onSelectTab = nav::switchTab,
            )
        }
        composable(PubRoutes.CERTIFICATE) {
            PubCertificateScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onSelectTab = nav::switchTab,
            )
        }
        composable(
            PubRoutes.RECORDS,
            enterTransition = { fadeIn(tween(220)) },
            exitTransition = { fadeOut(tween(160)) },
            popEnterTransition = { fadeIn(tween(220)) },
            popExitTransition = { fadeOut(tween(160)) },
        ) {
            PubRecordsScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
                onSelectTab = nav::switchTab,
            )
        }
        composable(
            PubRoutes.ME,
            enterTransition = { fadeIn(tween(220)) },
            exitTransition = { fadeOut(tween(160)) },
            popEnterTransition = { fadeIn(tween(220)) },
            popExitTransition = { fadeOut(tween(160)) },
        ) {
            PubMeScreen(
                vm = vm,
                onOpenRecords = { nav.navigate(PubRoutes.RECORDS) },
                onOpenServer = { nav.navigate(PubRoutes.SETTINGS) },
                onOpenInfo = { key -> nav.navigate(PubRoutes.info(key)) },
                onSelectTab = nav::switchTab,
            )
        }
        composable(PubRoutes.LEARN) {
            PubLearnScreen(
                onBack = { nav.popBackStack() },
                onOpenArticle = { i -> nav.navigate(PubRoutes.article(i)) },
                onSelectTab = nav::switchTab,
            )
        }
        composable(PubRoutes.SETTINGS) {
            PubServerScreen(
                vm = vm,
                onBack = { nav.popBackStack() },
            )
        }
        composable(PubRoutes.INFO) { entry ->
            PubInfoScreen(
                infoKey = entry.arguments?.getString("key") ?: "about",
                onBack = { nav.popBackStack() },
            )
        }
        composable(PubRoutes.ARTICLE) { entry ->
            PubArticleScreen(
                index = entry.arguments?.getString("index")?.toIntOrNull() ?: 0,
                onBack = { nav.popBackStack() },
            )
        }
    }
    }
}
