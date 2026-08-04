const MODEL_ORDER = ['LIDMark', 'KAD-Net', 'SepMark', 'WaveGuard'];
const REASON_LABELS = {
  checkpoint_unavailable_or_hash_mismatch: 'checkpoint 缺失或哈希不符',
  checkpoint_unregistered: '未登记',
  calibration_unverified: '校准未验收',
  weight_manifest_untrusted: '清单未验签',
};

function fail(message) { throw { code: 'invalid_model_status', message }; }
function isHash(value) { return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value); }

function validateModelStatus(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)
      || payload.schema_version !== 'model-provenance-status.v1') {
    fail('模型状态 schema 不匹配');
  }
  const options = MODEL_ORDER.map((name) => {
    const value = payload[name];
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail(name + ' 状态缺失');
    ['available', 'loaded', 'registered', 'calibrated', 'trusted', 'provenance_ready'].forEach((key) => {
      if (typeof value[key] !== 'boolean') fail(name + '.' + key + ' 必须为布尔值');
    });
    if (!isHash(value.checkpoint_sha256)) fail(name + ' checkpoint SHA-256 无效');
    if (value.calibrated) {
      if (typeof value.verification_threshold !== 'number'
          || !Number.isFinite(value.verification_threshold)
          || value.verification_threshold < 0 || value.verification_threshold > 1) {
        fail(name + ' 校准阈值无效');
      }
    } else if (value.verification_threshold !== null) {
      fail(name + ' 未校准时阈值必须为空');
    }
    if (!Array.isArray(value.reason_codes)
        || new Set(value.reason_codes).size !== value.reason_codes.length
        || value.reason_codes.some((code) => !REASON_LABELS[code])) {
      fail(name + ' 阻断原因无效');
    }
    const ready = value.available && value.registered && value.calibrated && value.trusted;
    if (value.provenance_ready !== ready) fail(name + ' provenance_ready 与子门禁不一致');
    const required = [
      !value.available && 'checkpoint_unavailable_or_hash_mismatch',
      !value.registered && 'checkpoint_unregistered',
      !value.calibrated && 'calibration_unverified',
      !value.trusted && 'weight_manifest_untrusted',
    ].filter(Boolean);
    if (required.some((code) => value.reason_codes.indexOf(code) === -1)
        || (ready && value.reason_codes.length)) {
      fail(name + ' 阻断原因未完整解释门禁');
    }
    return {
      name,
      provenanceReady: ready,
      reasonCodes: value.reason_codes.slice(),
      reason: ready ? 'registered + calibrated + trusted' : value.reason_codes.map((code) => REASON_LABELS[code]).join('、'),
      shortReason: ready ? '可发布' : value.reason_codes.map((code) => REASON_LABELS[code]).join(' / '),
      threshold: value.verification_threshold,
    };
  });
  const ready = options.filter((item) => item.provenanceReady);
  const preferredModel = ready.length ? ready[0].name : null;
  if (payload.preferred_model !== preferredModel) fail('preferred_model 未指向首个可信模型');
  return { options, preferredModel };
}

module.exports = { MODEL_ORDER, REASON_LABELS, validateModelStatus };
