package com.vpsg.jianyuanshield.core

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import java.io.ByteArrayOutputStream
import java.io.IOException

/** 上传前对图片降采样 + JPEG 压缩,减小流量与等待。 */
object ImageCompressor {

    /** 返回压缩后的 JPEG 字节;失败抛 IOException。 */
    fun compress(context: Context, uri: Uri, maxEdge: Int = 1280, quality: Int = 85): ByteArray {
        val resolver = context.contentResolver

        // 1) 先量尺寸,算出 inSampleSize(2 的幂),省内存
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        val longEdge = maxOf(bounds.outWidth, bounds.outHeight)
        var sample = 1
        if (longEdge > 0) {
            while (longEdge / (sample * 2) >= maxEdge) sample *= 2
        }

        val opts = BitmapFactory.Options().apply { inSampleSize = sample }
        val decoded = resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
            ?: throw IOException("无法读取所选图片")

        val scaled = scaleDown(decoded, maxEdge)
        val out = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, quality, out)
        scaled.recycle()
        if (scaled !== decoded) decoded.recycle()
        return out.toByteArray()
    }

    /** 解码一张小缩略图(用于历史记录);失败返回 null。 */
    fun decodeThumbnail(context: Context, uri: Uri, maxEdge: Int = 320): Bitmap? = runCatching {
        val resolver = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        val longEdge = maxOf(bounds.outWidth, bounds.outHeight)
        var sample = 1
        if (longEdge > 0) {
            while (longEdge / (sample * 2) >= maxEdge) sample *= 2
        }
        val opts = BitmapFactory.Options().apply { inSampleSize = sample }
        val decoded = resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
            ?: return null
        val scaled = scaleDown(decoded, maxEdge)
        if (scaled !== decoded) decoded.recycle()
        scaled
    }.getOrNull()

    private fun scaleDown(src: Bitmap, maxEdge: Int): Bitmap {
        val longEdge = maxOf(src.width, src.height)
        if (longEdge <= maxEdge || longEdge == 0) return src
        val scale = maxEdge.toFloat() / longEdge
        val w = (src.width * scale).toInt().coerceAtLeast(1)
        val h = (src.height * scale).toInt().coerceAtLeast(1)
        return Bitmap.createScaledBitmap(src, w, h, true)
    }
}
