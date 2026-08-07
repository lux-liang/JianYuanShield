// 数值格式化与阈值着色（与 Web 端 fmtScore 同阈值：≥0.95 绿 / ≥0.8 琥珀 / 否则红）
function finiteNumber(v) {
  if (v == null || typeof v === 'boolean' || (typeof v === 'string' && !v.trim())) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function pct(v, d) {
  const n = finiteNumber(v);
  return n == null ? '—' : (n * 100).toFixed(d == null ? 1 : d) + '%';
}
function scoreClass(v) {
  const n = finiteNumber(v);
  if (n == null) return 'muted';
  return n >= 0.95 ? 'ok' : n >= 0.8 ? 'warn' : 'risk';
}
function fixed(v, d) {
  const n = finiteNumber(v);
  return n == null ? '—' : n.toFixed(d == null ? 1 : d);
}
// 从 infer-single.v1 的 metrics 中取主精度（tracer > c > detector > bit_accuracy）
function pickAcc(m) {
  if (!m) return null;
  if (m.bit_accuracy_tracer != null) return m.bit_accuracy_tracer;
  if (m.bit_accuracy_c != null) return m.bit_accuracy_c;
  if (m.bit_accuracy_detector != null) return m.bit_accuracy_detector;
  return m.bit_accuracy != null ? m.bit_accuracy : null;
}
module.exports = { finiteNumber, pct, scoreClass, fixed, pickAcc };
