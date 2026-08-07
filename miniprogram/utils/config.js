// 后端地址必须通过 HTTPS 域名显式配置。仓库不提供默认公网地址，避免把
// 用户图片静默发送到未知服务器。
//
// 配置方式（二选一）：
// 1. 发布构建时填写 BUILD_API_BASE；
// 2. 通过微信 extConfig 提供 jysApiBase/apiBase（推荐多环境发布）。
const BUILD_API_BASE = '';

function readExtConfig() {
  try {
    if (typeof wx !== 'undefined' && typeof wx.getExtConfigSync === 'function') {
      return wx.getExtConfigSync() || {};
    }
  } catch (e) {}
  return {};
}

function normalizeApiBase(value) {
  const raw = String(value || '').trim().replace(/\/+$/, '');
  if (!raw) {
    return {
      ok: false,
      base: '',
      code: 'api_base_not_configured',
      message: '后端 HTTPS 地址未配置，请在 utils/config.js 或 extConfig 中设置 jysApiBase。',
    };
  }
  if (!/^https:\/\/[^/?#\s]+(?:\/[^?#\s]*)?$/.test(raw)) {
    return {
      ok: false,
      base: '',
      code: 'invalid_api_base',
      message: '后端地址必须是无查询参数的 HTTPS 地址。',
    };
  }
  const authority = raw.slice('https://'.length).split('/')[0];
  const registeredDomain = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$/i;
  if (authority.includes('@') || !registeredDomain.test(authority)) {
    return {
      ok: false,
      base: '',
      code: 'invalid_api_host',
      message: '后端必须使用已备案并加入微信合法域名列表的标准 HTTPS 域名，不能使用 IP、localhost、自定义端口或含凭据地址。',
    };
  }
  return { ok: true, base: raw, code: '', message: '' };
}

const extConfig = readExtConfig();
const API_CONFIG = normalizeApiBase(extConfig.jysApiBase || extConfig.apiBase || BUILD_API_BASE);
const API_BASE = API_CONFIG.base;

function normalizeApiKey(value) {
  const raw = String(value || '').trim();
  return raw && raw.length <= 512 && /^[\x21-\x7e]+$/.test(raw) ? raw : '';
}

const API_KEY = normalizeApiKey(extConfig.jysApiKey);

function apiHeaders() {
  // 仅从发布环境 extConfig 注入，禁止把密钥写入仓库。小程序端密钥可被提取，
  // 正式生产应由用户会话/网关签发短期凭据，不能把此值当作长期秘密。
  return API_KEY ? { 'X-API-Key': API_KEY } : {};
}

function apiConfigStatus() {
  return Object.assign({}, API_CONFIG, { apiKeyConfigured: !!API_KEY });
}

function buildApiUrl(path) {
  if (!API_CONFIG.ok) {
    throw { code: API_CONFIG.code, message: API_CONFIG.message, path: path || '' };
  }
  if (typeof path !== 'string' || !/^\/api(?:\/|$)/.test(path) || /[\\?#]/.test(path)) {
    throw { code: 'invalid_api_path', message: '无效的 API 路径', path: path || '' };
  }
  return API_CONFIG.base + path;
}

module.exports = { API_BASE, apiConfigStatus, apiHeaders, buildApiUrl, normalizeApiBase, normalizeApiKey };
