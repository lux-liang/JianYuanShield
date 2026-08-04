package com.vpsg.jianyuanshield.ui.screens.home

import androidx.compose.animation.Crossfade
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Analytics
import androidx.compose.material.icons.automirrored.rounded.FactCheck
import androidx.compose.material.icons.rounded.Fingerprint
import androidx.compose.material.icons.rounded.Gavel
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vpsg.jianyuanshield.data.UiState
import com.vpsg.jianyuanshield.ui.components.GlassPill
import com.vpsg.jianyuanshield.ui.components.SectionCard
import com.vpsg.jianyuanshield.ui.components.SectionHeader
import com.vpsg.jianyuanshield.ui.components.ServiceEntry
import com.vpsg.jianyuanshield.ui.components.StatusTone
import com.vpsg.jianyuanshield.ui.components.TaskCard
import com.vpsg.jianyuanshield.ui.components.TrustedEvidenceCard
import com.vpsg.jianyuanshield.ui.components.heroTexture
import com.vpsg.jianyuanshield.ui.foundation.PulseLoader
import com.vpsg.jianyuanshield.ui.foundation.entrance
import com.vpsg.jianyuanshield.ui.navigation.Routes
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.HeroEnd
import com.vpsg.jianyuanshield.ui.theme.HeroMid
import com.vpsg.jianyuanshield.ui.theme.HeroStart

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onNavigate: (String) -> Unit,
    viewModel: HomeViewModel = viewModel(factory = HomeViewModel.Factory),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val refreshing by viewModel.refreshing.collectAsStateWithLifecycle()

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = viewModel::refresh,
        modifier = Modifier.fillMaxSize(),
    ) {
        Crossfade(targetState = state, label = "home-state") { s ->
            when (s) {
                is UiState.Success -> HomeContent(s.data, onNavigate, onRefresh = viewModel::refresh)
                else -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    PulseLoader(text = "正在连接可信服务节点…")
                }
            }
        }
    }
}

@Composable
private fun HomeContent(data: HomeData, onNavigate: (String) -> Unit, onRefresh: () -> Unit) {
    val online = data.health?.ok == true
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
    ) {
        // ── 深蓝政务 Hero(数据网格 + 盾徽水印)──
        Column(
            Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .background(
                    androidx.compose.ui.graphics.Brush.verticalGradient(listOf(HeroStart, HeroMid, HeroEnd)),
                    RoundedCornerShape(bottomStart = 18.dp, bottomEnd = 18.dp),
                )
                .heroTexture()
                .padding(horizontal = 20.dp)
                .padding(top = 14.dp, bottom = 34.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("鉴源盾", style = MaterialTheme.typography.headlineMedium, color = Color.White)
                    Spacer(Modifier.height(2.dp))
                    Text("主动水印保护、登记与指定记录核验平台", style = MaterialTheme.typography.bodyMedium, color = Color.White.copy(alpha = 0.82f))
                }
                IconButton(onClick = onRefresh) {
                    Icon(Icons.Rounded.Refresh, contentDescription = "刷新", tint = Color.White)
                }
            }
            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (online) {
                    GlassPill("可信服务节点 · 已连接")
                    GlassPill("本地模型已加载")
                } else {
                    GlassPill("本地演示模式")
                    GlassPill("本地模型已加载")
                }
            }
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .offset(y = (-28).dp)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // ── 可信取证卡(视觉中心,半覆盖 Hero)──
            TrustedEvidenceCard(
                identity = "取证员 · 王*",
                deviceId = "JYD-2026-0042",
                algorithm = "Ed25519",
                chainStatus = "可用",
                todayTasks = 7,
                onNewTask = { onNavigate(Routes.INFER) },
                onOpenChain = { onNavigate(Routes.EVIDENCE) },
                modifier = Modifier.entrance(0),
            )

            // ── 核心服务(单列功能列表,短文案不截断;独立卡=区别于内容卡)──
            Column(
                Modifier.entrance(1),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                SectionHeader("核心服务", subtitle = "溯源、合规、核验、评测一体化")
                ServiceEntry(Icons.Rounded.Fingerprint, "链路评估", "单请求嵌入、攻击与恢复", GovBlue, { onNavigate(Routes.INFER) })
                ServiceEntry(Icons.AutoMirrored.Rounded.FactCheck, "合规检测", "隐式水印与标识核验", GovBlue, { onNavigate(Routes.COMPLIANCE) })
                ServiceEntry(Icons.Rounded.Gavel, "证据核验", "签名与文件哈希校验", GovBlue, { onNavigate(Routes.EVIDENCE) })
                ServiceEntry(Icons.Rounded.Analytics, "基准评测", "模型性能与鲁棒性评估", GovBlue, { onNavigate(Routes.BENCHMARK) })
            }

            // ── 最近取证任务 ──
            SectionCard(Modifier.entrance(2)) {
                SectionHeader("最近链路评估", subtitle = "近 7 日")
                Spacer(Modifier.height(4.dp))
                TaskCard(
                    taskId = "JYD-20260614-2237",
                    fileName = "IMG_20260614_2237.jpg",
                    time = "22:37",
                    pills = listOf("已归档" to StatusTone.Info, "低风险" to StatusTone.Success, "已签名" to StatusTone.Success),
                )
                androidx.compose.material3.HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                TaskCard(
                    taskId = "JYD-20260613-1904",
                    fileName = "IMG_20260613_1904.png",
                    time = "昨天 19:04",
                    pills = listOf("已归档" to StatusTone.Info, "中风险" to StatusTone.Warning, "已签名" to StatusTone.Success),
                )
            }

            // 服务状态明细统一收敛到「设置 · 模型服务」,首页不再重复(避免状态自相矛盾)。

            Spacer(Modifier.height(96.dp)) // 底部导航安全距离
        }
    }
}
