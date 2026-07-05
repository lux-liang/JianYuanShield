// 网络封装：统一拼接 API base、解析后端统一错误体 {ok:false,error:{code,message,path}}
const { API_BASE } = require('./config');

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: API_BASE + path,
      method: options.method || 'GET',
      data: options.data || {},
      header: Object.assign({ 'content-type': 'application/json' }, options.header || {}),
      timeout: options.timeout || 30000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(res.data);
        const e = (res.data && res.data.error) || {};
        reject({ code: e.code || ('http_' + res.statusCode), message: e.message || ('HTTP ' + res.statusCode), path });
      },
      fail(err) {
        reject({ code: 'network_error', message: (err && err.errMsg) || '网络错误', path });
      },
    });
  });
}

// multipart 上传：用于 /api/infer/single、/api/compliance/batch
function uploadFile(path, filePath, formData = {}, name = 'file') {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: API_BASE + path,
      filePath,
      name,
      formData,
      timeout: 60000,
      success(res) {
        let data = {};
        try { data = JSON.parse(res.data); }
        catch (e) { return reject({ code: 'invalid_json', message: '返回非 JSON', path }); }
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(data);
        const er = (data && data.error) || {};
        reject({ code: er.code || ('http_' + res.statusCode), message: er.message || ('HTTP ' + res.statusCode), path });
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
