// 本地任务历史：缩略图存为本地文件，元数据存 storage，最多 15 条。
// 旧版本未保存可信三元组，读取时必须按“不可引用”迁移。
const { resultTrust } = require('./trust');

const KEY = 'jys_history';
const MAX = 15;
const SCHEMA_VERSION = 2;
const KNOWN_SCENARIOS = ['protect', 'verify', 'infer_single', 'mea', 'compliance'];

function _rawLoad() {
  try {
    const value = wx.getStorageSync(KEY);
    return Array.isArray(value) ? value : [];
  } catch (e) { return []; }
}

function _scenario(value) {
  return KNOWN_SCENARIOS.indexOf(value) !== -1 ? value : 'legacy';
}

function _summary(scenario, trust, payload) {
  if (trust.citeable && scenario === 'protect') return '来源保护登记 · 可引用';
  if (trust.citeable && scenario === 'verify') {
    return payload.verified === true ? '登记来源匹配 · 可引用' : '登记来源未匹配 · 可引用';
  }
  if (scenario === 'protect') return '来源保护登记 · 不可引用';
  if (scenario === 'verify') return '登记来源核验 · 不可引用';
  if (scenario === 'infer_single' || scenario === 'mea') return '模型评估 · 不可引用';
  if (scenario === 'compliance') return '合规能力不可用 · 不可引用';
  if (scenario === 'legacy') return '历史旧记录 · 不可引用';
  if (trust.modeKind === 'unavailable') return '能力不可用 · 不可引用';
  return '历史旧记录 · 不可引用';
}

function normalize(item) {
  const value = item || {};
  const scenario = _scenario(value.scenario);
  const payload = {
    mode: value.mode,
    claim_valid: value.declaredClaimValid === true,
    result_provenance: value.resultProvenance,
    verified: value.verified === true,
  };
  const trust = resultTrust(payload, scenario);
  return {
    schemaVersion: SCHEMA_VERSION,
    t: Number(value.t) || Date.now(),
    model: String(value.model || '-'),
    attack: String(value.attack || '-'),
    accText: String(value.accText || '—'),
    accClass: String(value.accClass || 'muted'),
    thumb: String(value.thumb || ''),
    scenario,
    scenarioText: trust.scenarioText,
    contentId: String(value.contentId || ''),
    mode: trust.mode,
    modeText: trust.modeText,
    resultProvenance: trust.resultProvenance,
    provenanceText: trust.provenanceText,
    declaredClaimValid: trust.declaredClaimValid,
    claimValid: trust.citeable,
    citeable: trust.citeable,
    claimText: trust.claimText,
    claimClass: trust.claimClass,
    verdictText: _summary(scenario, trust, payload),
    verdictCls: trust.citeable ? 'ok' : 'risk',
    verified: payload.verified,
  };
}

function load() {
  return _rawLoad().map(normalize);
}

function _removeFile(path) {
  if (!path) return;
  try { wx.getFileSystemManager().removeSavedFile({ filePath: path }); } catch (e) {}
}

function _push(item) {
  try {
    const list = load();
    list.unshift(normalize(item));
    if (list.length > MAX) {
      const dropped = list.splice(MAX);
      dropped.forEach((value) => _removeFile(value.thumb));
    }
    wx.setStorageSync(KEY, list);
    return true;
  } catch (e) { return false; }
}

// meta: { imgPath, model, attack, accText, accClass, scenario, payload }
function add(meta) {
  const value = meta || {};
  const payload = value.payload || {};
  const base = {
    t: Date.now(),
    model: value.model || payload.model || '-',
    attack: value.attack || payload.attack || '-',
    accText: value.accText || '—',
    accClass: value.accClass || 'muted',
    scenario: _scenario(value.scenario),
    contentId: payload.content_id || '',
    mode: payload.mode,
    resultProvenance: payload.result_provenance,
    declaredClaimValid: payload.claim_valid === true,
    verified: payload.verified === true,
    thumb: '',
  };
  if (!value.imgPath) { _push(base); return Promise.resolve(); }
  return new Promise((resolve) => {
    const fs = wx.getFileSystemManager();
    const finish = (item) => { _push(item); resolve(); };
    const persist = (tmp) => fs.saveFile({
      tempFilePath: tmp,
      success: (result) => finish(Object.assign(base, { thumb: result.savedFilePath })),
      fail: () => finish(base),
    });
    try {
      wx.compressImage({
        src: value.imgPath,
        quality: 55,
        success: (compressed) => persist(compressed.tempFilePath),
        fail: () => persist(value.imgPath),
      });
    } catch (e) { finish(base); }
  });
}

function clear() {
  load().forEach((value) => _removeFile(value.thumb));
  try { wx.removeStorageSync(KEY); } catch (e) {}
}

module.exports = { SCHEMA_VERSION, add, clear, load, normalize };
