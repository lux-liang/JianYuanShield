// 检测历史：本地持久化（缩略图压缩后存为本地文件，元数据存 storage），限 15 条
const KEY = 'jys_history';
const MAX = 15;

function load() {
  try { return wx.getStorageSync(KEY) || []; } catch (e) { return []; }
}

function _removeFile(p) {
  if (!p) return;
  try { wx.getFileSystemManager().removeSavedFile({ filePath: p }); } catch (e) {}
}

function _push(item) {
  try {
    const list = load();
    list.unshift(item);
    if (list.length > MAX) {
      const dropped = list.splice(MAX);
      dropped.forEach((d) => _removeFile(d.thumb));
    }
    wx.setStorageSync(KEY, list);
  } catch (e) {}
}

// meta: { imgPath, model, attack, accText, accClass, verdictText, verdictCls }
function add(meta) {
  const base = {
    t: Date.now(),
    model: meta.model || '-', attack: meta.attack || '-',
    accText: meta.accText || '—', accClass: meta.accClass || 'muted',
    verdictText: meta.verdictText || '—', verdictCls: meta.verdictCls || 'info',
    thumb: '',
  };
  if (!meta.imgPath) { _push(base); return; }
  const fs = wx.getFileSystemManager();
  const persist = (tmp) => fs.saveFile({
    tempFilePath: tmp,
    success: (r) => _push(Object.assign(base, { thumb: r.savedFilePath })),
    fail: () => _push(base),
  });
  wx.compressImage({
    src: meta.imgPath, quality: 55,
    success: (c) => persist(c.tempFilePath),
    fail: () => persist(meta.imgPath),
  });
}

function clear() {
  load().forEach((d) => _removeFile(d.thumb));
  try { wx.removeStorageSync(KEY); } catch (e) {}
}

module.exports = { load, add, clear };
