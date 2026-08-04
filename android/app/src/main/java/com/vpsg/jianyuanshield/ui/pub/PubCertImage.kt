package com.vpsg.jianyuanshield.ui.pub

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import com.vpsg.jianyuanshield.core.QrEncoder

/** 把一次鉴别结果渲染成一张可保存 / 分享的凭证位图(纯 android.graphics,确定性、可静态核验)。 */
object PubCertImage {

    private const val W = 1080
    private const val M = 56f
    private const val HEADER_H = 230f

    fun render(ui: PubResultUi, qrContent: String?): Bitmap {
        require(ui.canIssueCertificate) {
            "Only registered blind-verification, claim-valid, real-checkpoint results may generate a certificate"
        }
        val bodyW = W - 2 * M

        // 文案画笔
        val descPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF4E5D77.toInt(); textSize = 30f }
        val footPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF97A2B8.toInt(); textSize = 24f }
        val descLayout = staticLayout(ui.desc, descPaint, bodyW.toInt())
        val footText = "技术支持 · 新疆大学 VPSG 实验室 · 技术核验记录，非司法鉴定"
        val footLayout = staticLayout(footText, footPaint, bodyW.toInt())

        // 动态计算总高
        var h = HEADER_H + 44f      // header + gap
        h += 96f                    // verdict chip + title row
        h += descLayout.height + 30f
        h += 2f + 28f               // divider
        h += 4 * 60f                // KV 4 行
        h += 28f + 2f + 28f         // divider
        h += 320f                   // QR 区
        h += 24f
        h += footLayout.height + 48f
        val H = h.toInt()

        val bmp = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        c.drawColor(Color.WHITE)

        val p = Paint(Paint.ANTI_ALIAS_FLAG)

        // ── header 蓝渐变 ──
        p.shader = LinearGradient(0f, 0f, W.toFloat(), HEADER_H, 0xFF3A6FEC.toInt(), 0xFF23399E.toInt(), Shader.TileMode.CLAMP)
        c.drawRect(0f, 0f, W.toFloat(), HEADER_H, p)
        p.shader = null

        val title = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE; textSize = 46f; typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        }
        c.drawText("鉴源盾 · 来源核验凭证", M, 96f, title)
        val sub = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xCCFFFFFF.toInt(); textSize = 24f }
        c.drawText("WATERMARK VERIFICATION RECORD", M, 138f, sub)
        c.drawText("编号 ${ui.certNumber}", M, 188f, sub)

        var y = HEADER_H + 64f

        // ── 结论 chip + 标题 ──
        val (chipBg, chipFg) = verdictColors(ui.verdict)
        val chipPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = chipBg }
        val chipText = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = chipFg; textSize = 30f; typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        }
        val chipLabel = ui.certBadge
        val chipTextW = chipText.measureText(chipLabel)
        val chipW = chipTextW + 48f
        val chipH = 56f
        c.drawRoundRect(RectF(M, y - chipH + 12f, M + chipW, y + 12f), 16f, 16f, chipPaint)
        c.drawText(chipLabel, M + 24f, y - 6f, chipText)

        val titleText = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = 0xFF0F1A2E.toInt(); textSize = 38f; typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        }
        c.drawText(ui.title, M + chipW + 24f, y + 4f, titleText)
        y += 58f

        // ── desc ──
        c.save(); c.translate(M, y); descLayout.draw(c); c.restore()
        y += descLayout.height + 30f

        // divider
        y = drawDivider(c, y)

        // ── KV ──
        val kv = listOf(
            "图片名称" to ui.certName,
            "评估时间" to ui.certTime,
            "评估项目" to ui.certItems,
            "评估引擎" to "鉴源盾 · ${ui.model}",
        )
        val kPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF97A2B8.toInt(); textSize = 28f }
        val vPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF0F1A2E.toInt(); textSize = 28f }
        for ((k, v) in kv) {
            c.drawText(k, M, y + 20f, kPaint)
            val vTrim = ellipsize(v, vPaint, bodyW - 220f)
            c.drawText(vTrim, M + 220f, y + 20f, vPaint)
            y += 60f
        }

        y += 28f
        y = drawDivider(c, y)

        // ── QR + 说明 ──
        val qrSize = 280f
        val qrTop = y
        drawQr(c, qrContent, M, qrTop, qrSize)
        val qrRightX = M + qrSize + 40f
        val qLabel = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = 0xFF0F1A2E.toInt(); textSize = 30f; typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        }
        c.drawText("扫码核对报告", qrRightX, qrTop + 50f, qLabel)
        val qDesc = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF4E5D77.toInt(); textSize = 24f }
        val qDescLayout = staticLayout(
            "扫码可在服务器核对本次主动水印验证报告(SHA-256 指纹一致表示报告未被改动)。",
            qDesc, (W - qrRightX - M).toInt(),
        )
        c.save(); c.translate(qrRightX, qrTop + 72f); qDescLayout.draw(c); c.restore()

        // SHA-256 指纹(取第一条)
        ui.sha256.firstOrNull()?.let { (k, v) ->
            val shaPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF97A2B8.toInt(); textSize = 22f }
            val shaShort = if (v.length > 32) "${v.take(16)}…${v.takeLast(12)}" else v
            c.drawText("指纹($k):$shaShort", qrRightX, qrTop + qrSize - 20f, shaPaint)
        }
        y = qrTop + qrSize + 24f

        // ── footer ──
        c.save(); c.translate(M, y); footLayout.draw(c); c.restore()

        return bmp
    }

    private fun drawDivider(c: Canvas, y: Float): Float {
        val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFEBEFF7.toInt() }
        c.drawRect(M, y, W - M, y + 2f, p)
        return y + 30f
    }

    private fun drawQr(c: Canvas, content: String?, left: Float, top: Float, size: Float) {
        val border = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFEBEFF7.toInt(); style = Paint.Style.STROKE; strokeWidth = 2f }
        val matrix = content?.let { QrEncoder.encode(it, 256) }
        // 白底
        val white = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE }
        c.drawRect(left, top, left + size, top + size, white)
        if (matrix != null) {
            val n = matrix.width
            val cell = size / n
            val dark = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF0F1A2E.toInt() }
            for (yy in 0 until n) {
                for (xx in 0 until n) {
                    if (matrix.get(xx, yy)) {
                        c.drawRect(left + xx * cell, top + yy * cell, left + (xx + 1) * cell, top + (yy + 1) * cell, dark)
                    }
                }
            }
        } else {
            val tp = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF97A2B8.toInt(); textSize = 22f }
            c.drawText("二维码不可用", left + 30f, top + size / 2f, tp)
        }
        c.drawRect(left, top, left + size, top + size, border)
    }

    private fun verdictColors(v: VerdictKind): Pair<Int, Int> = when (v) {
        VerdictKind.Real -> 0xFFE7F6EF.toInt() to 0xFF13A06A.toInt()
        VerdictKind.Ai -> 0xFFFCF2DE.toInt() to 0xFFE0901F.toInt()
        VerdictKind.Tampered -> 0xFFFCEAE8.toInt() to 0xFFE0463C.toInt()
    }

    private fun staticLayout(text: String, paint: TextPaint, width: Int): StaticLayout =
        StaticLayout.Builder.obtain(text, 0, text.length, paint, width.coerceAtLeast(1))
            .setAlignment(Layout.Alignment.ALIGN_NORMAL)
            .setLineSpacing(6f, 1f)
            .setIncludePad(false)
            .build()

    private fun ellipsize(text: String, paint: Paint, maxWidth: Float): String {
        if (paint.measureText(text) <= maxWidth) return text
        var end = text.length
        while (end > 0 && paint.measureText(text.substring(0, end) + "…") > maxWidth) end--
        return text.substring(0, end) + "…"
    }
}
