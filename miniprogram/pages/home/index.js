// 单页立方体：取证/证据/我的/关于 = 4 个面，底部导航旋转切面
const { uploadFile, request, fmtErr, API_BASE } = require('../../utils/request');
const { pct, scoreClass, fixed, pickAcc } = require('../../utils/format');
const history = require('../../utils/history');

const MODELS = ['SepMark', 'WaveGuard'];
const ATTACKS = [
  { v: 'clean', t: '无攻击' }, { v: 'jpeg50', t: 'JPEG50' }, { v: 'jpeg70', t: 'JPEG70' },
  { v: 'resize', t: '缩放' }, { v: 'noise', t: '噪声' }, { v: 'blur', t: '模糊' },
];
const IMG_LABELS = { original: '原图', watermarked: '含水印', attacked: '被攻击', heatmap: '热力图', diff: '残差' };
const VERDICT = {
  compliant: { cls: 'ok', text: '✔ 合规水印已验证' },
  degraded: { cls: 'warn', text: '⚠ 水印降级（攻击后残留）' },
  no_watermark: { cls: 'risk', text: '✘ 未检测到合规水印' },
};
const STEPS = ['样本输入', '主动水印', '攻击链', '提取取证', '哈希存证'];
const NAVS = [
  { k: '取证', ic: '/assets/tab-forensics.png', on: '/assets/tab-forensics-on.png' },
  { k: '证据', ic: '/assets/tab-evidence.png', on: '/assets/tab-evidence-on.png' },
  { k: '我的', ic: '/assets/tab-profile.png', on: '/assets/tab-profile-on.png' },
  { k: '关于', ic: '/assets/tab-about.png', on: '/assets/tab-about-on.png' },
];

function ts(t) { const d = new Date(t); const p = (n) => String(n).padStart(2, '0'); return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }

Page({
  data: {
    // 立方体
    navs: NAVS, rotIdx: 0, rot: 0,
    showSplash: false,
    // 取证
    health: 'syncing', steps: STEPS, models: MODELS, attacks: ATTACKS,
    model: 'SepMark', attack: 'jpeg50', imgPath: '', loading: false, step: 1,
    result: null, imgs: [], accText: '—', accClass: 'muted', psnrText: '—',
    verdict: null, modeText: '', modeClass: 'warn', taskId: '',
    evidenceText: '', showEvidence: false, posterPath: '', error: '', scrollTo: '',
    // 证据
    sigOk: false, sigText: '连接中', fp: '', blocking: 0, findings: [], demoReady: false, claimsReady: false, auditErr: '',
    // 我的
    user: { avatar: '', nick: '' }, list: [], editing: false,
    // 首次强制登录
    needLogin: false, tmpAvatar: '', tmpNick: '',
    // 平台合规批量（内联在证据面）
    cFiles: [], cLoading: false, cSum: null, cRows: [], cModel: 'SepMark',
    // 关于
    wmModels: [
      { n: 'LIDMark', d: '空间域·152bit 关键点 · 语义绑定，Deepfake 后仍可溯源', t: '原创' },
      { n: 'KAD-Net', d: '空间域·KAN+SE · 30bit · 全场景', t: '' },
      { n: 'WaveGuard', d: '频域·DTCWT · 抗平台压缩', t: '' },
      { n: 'SepMark', d: '频域·分离子带 · 30bit', t: '' },
    ],
    regs: [
      { c: '第六条', d: '隐式标识（不可见水印）' }, { c: '第七条', d: '稳健抗干扰，传播后可识别' },
      { c: '第八条', d: '支持监管机构溯源查验' }, { c: '第十二条', d: '建立内容可信体系' },
    ],
  },

  onLoad() {
    const app = getApp();
    if (app && app.globalData && !app.globalData.splashShown) this.setData({ showSplash: true });
    const u = wx.getStorageSync('jys_user') || { avatar: '', nick: '' };
    if (!u.avatar || !u.nick) this.setData({ needLogin: true, tmpAvatar: u.avatar || '', tmpNick: u.nick || '' });
    this.checkHealth();
    this.loadAudit();
  },

  /* ── 首次强制登录 ── */
  onObAvatar(e) {
    const url = e.detail.avatarUrl;
    wx.getFileSystemManager().saveFile({ tempFilePath: url, success: (r) => this.setData({ tmpAvatar: r.savedFilePath }), fail: () => this.setData({ tmpAvatar: url }) });
  },
  onObNick(e) { this.setData({ tmpNick: e.detail.value }); },
  obSubmit() {
    if (!this.data.tmpAvatar || !this.data.tmpNick) { wx.showToast({ title: '请设置头像和昵称', icon: 'none' }); return; }
    const u = { avatar: this.data.tmpAvatar, nick: this.data.tmpNick };
    wx.setStorageSync('jys_user', u);
    this.setData({ user: u, needLogin: false, rotIdx: 0, rot: 0 });
  },
  onShow() {
    const u = wx.getStorageSync('jys_user') || { avatar: '', nick: '' };
    this.setData({ user: u });
    this.refreshHistory();
  },

  /* ── 立方体导航 ── */
  switchFace(e) {
    const idx = Number(e.currentTarget.dataset.i);
    this.setData({ rotIdx: idx, rot: -idx * 90 });
  },
  onSplashDone() { const app = getApp(); if (app && app.globalData) app.globalData.splashShown = true; this.setData({ showSplash: false }); },
  onTap(e) { const fx = this.selectComponent('#tapfx'); if (fx && e && e.detail && e.detail.x != null) fx.burst(e.detail.x, e.detail.y); },

  /* ── 取证 ── */
  checkHealth() { request('/api/health').then((d) => this.setData({ health: d && d.ok ? 'ok' : 'bad' })).catch(() => this.setData({ health: 'bad' })); },
  onSelectModel(e) { this.setData({ model: e.currentTarget.dataset.v }); },
  onSelectAttack(e) { this.setData({ attack: e.currentTarget.dataset.v }); },
  chooseImage() {
    wx.chooseMedia({ count: 1, mediaType: ['image'], sourceType: ['album', 'camera'], sizeType: ['compressed'],
      success: (res) => this.setData({ imgPath: res.tempFiles[0].tempFilePath, result: null, error: '', step: 2 }) });
  },
  useSample() {
    wx.showLoading({ title: '载入样本…' });
    request('/api/samples').then((list) => {
      const s = Array.isArray(list) && list[0]; if (!s) throw { message: '无内置样本' };
      return new Promise((resolve, reject) => wx.downloadFile({ url: API_BASE + '/api/samples/' + s.id + '/image',
        success: (r) => (r.statusCode === 200 ? resolve(r.tempFilePath) : reject({ message: '样本下载失败' })), fail: reject }));
    }).then((tmp) => { wx.hideLoading(); this.setData({ imgPath: tmp, result: null, error: '', step: 2 }); })
      .catch((e) => { wx.hideLoading(); wx.showToast({ title: fmtErr(e), icon: 'none' }); });
  },
  runInfer() {
    if (!this.data.imgPath) { wx.showToast({ title: '请先选择图片', icon: 'none' }); return; }
    this.setData({ loading: true, error: '', step: 3, result: null, scrollTo: '' });
    uploadFile('/api/infer/single', this.data.imgPath, { model: this.data.model, attack: this.data.attack, return_b64: 'true' })
      .then((r) => this.renderResult(r)).catch((e) => this.setData({ loading: false, error: fmtErr(e), step: 2 }));
  },
  renderResult(r) {
    const b64 = r.artifacts_b64 || {};
    const imgs = ['original', 'watermarked', 'attacked', 'heatmap'].filter((k) => b64[k]).map((k) => ({ key: k, label: IMG_LABELS[k], src: 'data:image/png;base64,' + b64[k] }));
    const m = r.metrics || {}; const acc = pickAcc(m); const comp = r.compliance || {};
    const verdict = VERDICT[comp.verdict] || { cls: 'info', text: comp.verdict || '—' };
    const sha = (r.evidence && r.evidence.sha256) || {}; const isReal = r.mode === 'real_checkpoint';
    this.setData({
      loading: false, step: 5, result: r, imgs,
      accText: pct(acc), accClass: scoreClass(acc), psnrText: m.psnr != null ? fixed(m.psnr) + ' dB' : '—',
      verdict, modeText: isReal ? '✔ 真实模型' : '⚠ 模拟模式', modeClass: isReal ? 'ok' : 'warn', taskId: r.task_id || '',
      evidenceText: JSON.stringify({ task_id: r.task_id, model: r.model, attack: r.attack, metrics: m, compliance: comp, sha256: sha }, null, 2),
    });
    setTimeout(() => this.setData({ scrollTo: 'resultCard' }), 60);
    history.add({ imgPath: this.data.imgPath, model: r.model, attack: r.attack, accText: pct(acc), accClass: scoreClass(acc), verdictText: verdict.text, verdictCls: verdict.cls });
  },
  toggleEvidence() { this.setData({ showEvidence: !this.data.showEvidence }); },
  reset() { this.setData({ result: null, imgPath: '', step: 1, error: '', showEvidence: false, posterPath: '' }); },
  goMea() { wx.navigateTo({ url: '/pages/mea/index' }); },
  goCompliance() { this.setData({ rotIdx: 1, rot: -90 }); }, // 旋转到证据面（合规已内联）

  /* ── 平台合规批量（内联） ── */
  cSelModel(e) { this.setData({ cModel: e.currentTarget.dataset.v }); },
  cChoose() {
    wx.chooseMedia({ count: 9, mediaType: ['image'], sourceType: ['album'], sizeType: ['compressed'],
      success: (r) => this.setData({ cFiles: r.tempFiles.map((f) => f.tempFilePath), cSum: null, cRows: [] }) });
  },
  cRun() {
    const files = this.data.cFiles;
    if (!files.length) { wx.showToast({ title: '请先选择图片', icon: 'none' }); return; }
    this.setData({ cLoading: true, cSum: null, cRows: [] });
    const LABEL = { compliant: '✔ 合规', degraded: '⚠ 降级', no_watermark: '✘ 无水印', error: '失败' };
    const CLS = { compliant: 'ok', degraded: 'warn', no_watermark: 'risk', error: 'risk' };
    Promise.all(files.map((fp) =>
      uploadFile('/api/infer/single', fp, { model: this.data.cModel, attack: 'clean', return_b64: 'false' })
        .then((r) => {
          const m = r.metrics || {};
          const acc = m.bit_accuracy_c != null ? m.bit_accuracy_c : (m.bit_accuracy_detector != null ? m.bit_accuracy_detector : m.bit_accuracy);
          const v = (r.compliance || {}).verdict;
          return { src: fp, verdict: v, accText: acc != null ? pct(acc) : '—', cls: CLS[v] || 'info', label: LABEL[v] || v };
        })
        .catch(() => ({ src: fp, verdict: 'error', accText: '—', cls: 'risk', label: '失败' }))
    )).then((rows) => {
      const compliant = rows.filter((r) => r.verdict === 'compliant').length;
      const degraded = rows.filter((r) => r.verdict === 'degraded').length;
      const no_wm = rows.filter((r) => r.verdict === 'no_watermark').length;
      this.setData({ cLoading: false, cRows: rows, cSum: { total: rows.length, compliant, degraded, no_wm, rate: pct(rows.length ? compliant / rows.length : 0, 0) } });
    }).catch(() => this.setData({ cLoading: false }));
  },
  onShareAppMessage() { return { title: '寻源路 · AIGC 图像水印溯源演示', path: '/pages/home/index' }; },

  /* ── 证据 ── */
  loadAudit() {
    request('/api/evidence/audit').then((a) => {
      const sig = a.signature || {};
      this.setData({ sigOk: !!sig.verified, sigText: sig.verified ? 'Ed25519 已验签' : (sig.status || '未生成'),
        fp: (sig.public_key_fingerprint_sha256 || '').slice(0, 24), blocking: (a.blocking_findings || []).length,
        findings: (a.findings || []).map((f) => ({ code: f.code, msg: f.message, sev: f.severity })),
        demoReady: !!a.ready_for_demo, claimsReady: !!a.ready_for_claims, auditErr: '' });
    }).catch((e) => this.setData({ auditErr: fmtErr(e), sigText: '不可用' }));
  },

  /* ── 我的 ── */
  refreshHistory() { const raw = history.load(); this.setData({ list: raw.map((x) => Object.assign({}, x, { timeText: ts(x.t) })) }); },
  onChooseAvatar(e) {
    const url = e.detail.avatarUrl;
    const save = (p) => { const u = Object.assign({}, this.data.user, { avatar: p }); this.setData({ user: u }); wx.setStorageSync('jys_user', u); };
    wx.getFileSystemManager().saveFile({ tempFilePath: url, success: (r) => save(r.savedFilePath), fail: () => save(url) });
  },
  startEdit() { this.setData({ editing: true }); },
  onNick(e) { const u = Object.assign({}, this.data.user, { nick: e.detail.value }); this.setData({ user: u, editing: false }); wx.setStorageSync('jys_user', u); },
  clearHistory() { wx.showModal({ title: '清空历史', content: '确定清空全部检测记录？', success: (m) => { if (m.confirm) { history.clear(); this.refreshHistory(); } } }); },

  /* 生成 / 保存海报 */
  generatePoster() {
    const r = this.data.result; if (!r) return;
    wx.showLoading({ title: '生成中…' });
    wx.createSelectorQuery().in(this).select('#posterCanvas').fields({ node: true, size: true }).exec((res) => {
      if (!res || !res[0] || !res[0].node) { wx.hideLoading(); wx.showToast({ title: '画布未就绪', icon: 'none' }); return; }
      const canvas = res[0].node; const ctx = canvas.getContext('2d');
      const info = (wx.getWindowInfo && wx.getWindowInfo()) || wx.getSystemInfoSync(); const dpr = (info && info.pixelRatio) || 2;
      const W = 600, H = 920; canvas.width = W * dpr; canvas.height = H * dpr; ctx.scale(dpr, dpr);
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#0369a1'; ctx.fillRect(0, 0, W, 10);
      ctx.textAlign = 'left';
      ctx.fillStyle = '#0b2a45'; ctx.font = 'bold 46px sans-serif'; ctx.fillText('寻源路', 44, 100);
      ctx.fillStyle = '#5a6b81'; ctx.font = '24px sans-serif'; ctx.fillText('AIGC 图像水印主动溯源', 44, 140);
      const vy = 200; ctx.strokeStyle = '#e3eaf3'; ctx.lineWidth = 2; ctx.strokeRect(44, vy, W - 88, 270);
      ctx.fillStyle = '#5a6b81'; ctx.font = '24px sans-serif'; ctx.fillText('Bit Accuracy', 76, vy + 56);
      ctx.fillStyle = '#0369a1'; ctx.font = 'bold 100px sans-serif'; ctx.fillText(this.data.accText, 72, vy + 165);
      ctx.fillStyle = '#0b2a45'; ctx.font = '30px sans-serif'; ctx.fillText((this.data.verdict && this.data.verdict.text) || '', 76, vy + 230);
      ctx.fillStyle = '#5a6b81'; ctx.font = '24px sans-serif';
      ctx.fillText('模型 ' + (r.model || '-') + '   攻击 ' + (r.attack || '-'), 44, 550);
      ctx.fillText('模式 ' + (r.mode || '-'), 44, 592); ctx.fillText('PSNR ' + this.data.psnrText, 44, 634);
      ctx.fillText('任务 ' + (r.task_id || '-'), 44, 676);
      ctx.fillStyle = '#0369a1'; ctx.font = '22px sans-serif'; ctx.fillText('主动水印 · 深度伪造溯源 · Ed25519 证据链', 44, 850);
      ctx.fillStyle = '#93a3b8'; ctx.font = '20px sans-serif'; ctx.fillText('新疆大学 VPSG · 技术演示作品', 44, 884);
      wx.canvasToTempFilePath({ canvas, success: (out) => { this.setData({ posterPath: out.tempFilePath }); wx.hideLoading(); }, fail: () => { wx.hideLoading(); wx.showToast({ title: '生成失败', icon: 'none' }); } });
    });
  },
  savePoster() {
    if (!this.data.posterPath) return;
    wx.saveImageToPhotosAlbum({ filePath: this.data.posterPath, success: () => wx.showToast({ title: '已保存到相册' }),
      fail: (e) => { if (/deny|authorize|auth/.test((e && e.errMsg) || '')) { wx.showModal({ title: '需要相册权限', content: '请在设置中允许“保存到相册”', success: (m) => { if (m.confirm) wx.openSetting(); } }); } else { wx.showToast({ title: '保存失败', icon: 'none' }); } } });
  },
});
