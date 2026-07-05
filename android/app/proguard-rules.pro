# ── kotlinx.serialization ────────────────────────────────────────────────────
# Keep generated serializers and the @Serializable annotated classes' companions.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**

-keepclassmembers class **$$serializer { *; }
-keepclassmembers @kotlinx.serialization.Serializable class * {
    *** Companion;
    *** INSTANCE;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.vpsg.jianyuanshield.**$$serializer { *; }
-keep @kotlinx.serialization.Serializable class com.vpsg.jianyuanshield.** { *; }

# ── Retrofit / OkHttp ────────────────────────────────────────────────────────
-keepattributes Signature, Exceptions
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn retrofit2.**
-keep,allowobfuscation,allowshrinking interface retrofit2.Call
-keep,allowobfuscation,allowshrinking class retrofit2.Response
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation

# ── Jetpack Compose ──────────────────────────────────────────────────────────
# Compose 库(runtime/ui)自带 consumer R8 规则,@Composable 不会被裁剪;
# 这里仅消除告警 + 防御性保留 @Composable 方法,避免 release 混淆异常。
-dontwarn androidx.compose.**
-keepclassmembers class * {
    @androidx.compose.runtime.Composable <methods>;
}
