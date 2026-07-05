package com.vpsg.jianyuanshield.core

import androidx.lifecycle.ViewModelProvider.AndroidViewModelFactory.Companion.APPLICATION_KEY
import androidx.lifecycle.viewmodel.CreationExtras
import com.vpsg.jianyuanshield.JianYuanShieldApp

/** Resolve the Application from ViewModel [CreationExtras]. */
fun CreationExtras.app(): JianYuanShieldApp = this[APPLICATION_KEY] as JianYuanShieldApp

/** Resolve the shared [AppContainer] inside a viewModelFactory initializer. */
fun CreationExtras.container(): AppContainer = app().container
