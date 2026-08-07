// 网络封装：统一拼接 API base、解析后端统一错误体 {ok:false,error:{code,message,path}}
const { API_BASE, apiHeaders, buildApiUrl } = require('./config');

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    let url;
    try { url = buildApiUrl(path); }
    catch (e) { reject(e); return; }
    wx.request({
      url,
      method: options.method || 'GET',
      data: options.data || {},
      header: Object.assign({ 'content-type': 'application/json' }, apiHeaders(), options.header || {}),
      timeout: options.timeout || 30000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(res.data);
        const e = (res.data && res.data.error) || {};
        const detail = res.data && res.data.detail;
        reject({ code: e.code || ('http_' + res.statusCode), message: e.message || (typeof detail === 'string' ? detail : '') || ('HTTP ' + res.statusCode), path });
      },
      fail(err) {
        reject({ code: 'network_error', message: (err && err.errMsg) || '网络错误', path });
      },
    });
  });
}

// multipart 上传：用于来源保护/核验与模型工程评估。
function uploadFile(path, filePath, formData = {}, name = 'file') {
  return new Promise((resolve, reject) => {
    let url;
    try { url = buildApiUrl(path); }
    catch (e) { reject(e); return; }
    wx.uploadFile({
      url,
      filePath,
      name,
      formData,
      header: apiHeaders(),
      timeout: 60000,
      success(res) {
        let data = {};
        try { data = JSON.parse(res.data); }
        catch (e) { return reject({ code: 'invalid_json', message: '返回非 JSON', path }); }
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(data);
        const er = (data && data.error) || {};
        const detail = data && data.detail;
        reject({ code: er.code || ('http_' + res.statusCode), message: er.message || (typeof detail === 'string' ? detail : '') || ('HTTP ' + res.statusCode), path });
      },
      fail(err) {
        reject({ code: 'network_error', message: (err && err.errMsg) || '上传失败', path });
      },
    });
  });
}

function fmtErr(e) {
  if (!e) return '未知错误';
  return (e.code ? e.code + ': ' : '') + (e.message || '请求失败');
}

module.exports = { request, uploadFile, fmtErr, API_BASE };
