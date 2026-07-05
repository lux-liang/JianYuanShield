package com.vpsg.jianyuanshield.core

import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.common.BitMatrix
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel

/** 用 zxing 生成真实可扫的二维码点阵。失败返回 null(调用方回退占位图)。 */
object QrEncoder {
    fun encode(content: String, size: Int = 512): BitMatrix? = runCatching {
        val hints = mapOf(
            EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M,
            EncodeHintType.MARGIN to 1,
            EncodeHintType.CHARACTER_SET to "UTF-8",
        )
        QRCodeWriter().encode(content, BarcodeFormat.QR_CODE, size, size, hints)
    }.getOrNull()
}
