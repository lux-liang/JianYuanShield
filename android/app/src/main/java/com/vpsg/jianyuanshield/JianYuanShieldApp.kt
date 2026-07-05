package com.vpsg.jianyuanshield

import android.app.Application
import com.vpsg.jianyuanshield.core.AppContainer

class JianYuanShieldApp : Application() {

    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
