package com.vpsg.jianyuanshield

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.vpsg.jianyuanshield.ui.pub.PubApp
import com.vpsg.jianyuanshield.ui.theme.JianYuanShieldTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            JianYuanShieldTheme {
                // 公众版界面(引导页 + 主流程)。旧的政务版 AppNavHost 仍保留在源码中,
                // 如需切回把这里换成 AppNavHost() 即可。
                PubApp()
            }
        }
    }
}
