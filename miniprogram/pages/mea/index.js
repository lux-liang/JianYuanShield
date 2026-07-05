const { uploadFile, fmtErr } = require('../../utils/request');
const { pct, scoreClass, fixed, pickAcc } = require('../../utils/format');

const MODELS = ['SepMark', 'WaveGuard'];
const ATTACKS = [
  { v: 'jpeg50', t: 'JPEG50' },
  { v: 'jpeg70', t: 'JPEG70' },
  { v: 'resize', t: '缩放' },
  { v: 'noise', t: '噪声' },
  { v: 'clean', t: '无攻击' },
];
const VERDICT = {
  compliant: { cls: 'ok', t: '✔ 合规' },
  degraded: { cls: 'warn', t: '⚠ 降级' },
  no_watermark: { cls: 'risk', t: '✘ 无水印' },
};
const IMG_LABELS = { watermarked: '含水印', attacked: '被攻击', heatmap: '热力图' };

Page({
  data: { attacks: ATTACKS, attack: 'jpeg50', imgPath: '', loading: false, cards: [], error: '' },

  chooseImage() {
    wx.chooseMedia({
      count: 1, mediaType: ['image'], sourceType: ['album', 'camera'], sizeType: ['compressed'],
      success: (r) => this.setData({ imgPath: r.tempFiles[0].tempFilePath, cards: [], error: '' }),
    });
  },
  onSelectAttack(e) { this.setData({ attack: e.currentTarget.dataset.v }); },

  run() {
    if (!this.data.imgPath) { wx.showToast({ title: '请先选择图片', icon: 'none' }); return; }
    this.setData({ loading: true, error: '', cards: [] });
    Promise.all(MODELS.map((model) =>
      uploadFile('/api/infer/single', this.data.imgPath, { model, attack: this.data.attack, return_b64: 'true' })
        .then((r) => {
          const b64 = r.artifacts_b64 || {};
          const m = r.metrics || {};
          const acc = pickAcc(m);
          const comp = r.compliance || {};
          return {
            model, acc: pct(acc), accClass: scoreClass(acc),
            psnr: m.psnr != null ? fixed(m.psnr) + ' dB' : '—',
            verdict: VERDICT[comp.verdict] || { cls: 'info', t: comp.verdict || '—' },
            imgs: ['watermarked', 'attacked', 'heatmap'].filter((k) => b64[k]).map((k) => ({ k, label: IMG_LABELS[k], src: 'data:image/png;base64,' + b64[k] })),
          };
        })
        .catch(() => ({ model, acc: '—', accClass: 'muted', psnr: '—', verdict: { cls: 'risk', t: '失败' }, imgs: [] }))
    )).then((cards) => this.setData({ loading: false, cards }))
      .catch((e) => this.setData({ loading: false, error: fmtErr(e) }));
  },

  onShareAppMessage() { return { title: '寻源路 · 多模型横评对比', path: '/pages/mea/index' }; },
});
