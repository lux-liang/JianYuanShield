// 单页立方体：来源保护/证据审计/我的/关于 = 4 个面，底部导航旋转切面。
const { uploadFile, request, fmtErr } = require('../../utils/request');
const { apiConfigStatus, apiHeaders, buildApiUrl } = require('../../utils/config');
const { resultTrust } = require('../../utils/trust');
const { pct, scoreClass, fixed, pickAcc } = require('../../utils/format');
const { MODEL_ORDER, validateModelStatus } = require('../../utils/model-status');
const history = require('../../utils/history');

const ATTACKS = [
  { v: 'clean', t: '无攻击' }, { v: 'jpeg50', t: 'JPEG50' }, { v: 'jpeg70', t: 'JPEG70' },
  { v: 'resize', t: '缩放' }, { v: 'noise', t: '噪声' }, { v: 'blur', t: '模糊' },
];
const IMG_LABELS = {
  original: '原图', watermarked: '含水印', attacked: '攻击模拟图', heatmap: '热力图', protected: '已登记保护图',
};
const STEPS = ['选择内容', '保护登记', '受控传播', '登记核验', '可信门禁'];
const NAVS = [
  { k: '保护', ic: '/assets/tab-forensics.png', on: '/assets/tab-forensics-on.png' },
  { k: '审计', ic: '/assets/tab-evidence.png', on: '/assets/tab-evidence-on.png' },
  { k: '我的', ic: '/assets/tab-profile.png', on: '/assets/tab-profile-on.png' },
  { k: '关于', ic: '/assets/tab-about.png', on: '/assets/tab-about-on.png' },
];

function ts(value) {
  const date = new Date(value);
  const pad = (number) => String(number).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function writeProtectedPng(encoded, contentId) {
  return new Promise((resolve, reject) => {
    if (!encoded) { resolve(''); return; }
    const safeId = /^[a-f0-9]{32}$/.test(contentId || '') ? contentId : String(Date.now());
    const filePath = `${wx.env.USER_DATA_PATH}/jys-protected-${safeId}.png`;
    wx.getFileSystemManager().writeFile({
      filePath,
      data: encoded,
      encoding: 'base64',
      success: () => resolve(filePath),
      fail: reject,
    });
  });
}

function removeGeneratedProtected(path) {
  if (!path) return;
  const prefix = `${wx.env.USER_DATA_PATH}/jys-protected-`;
  if (String(path).indexOf(prefix) !== 0) return;
  try { wx.getFileSystemManager().unlink({ filePath: path }); } catch (e) {}
}

function provenanceEvidence(result, trust, scenario) {
  const value = result || {};
  return {
    scenario,
    mode: trust.mode,
    declared_claim_valid: trust.declaredClaimValid,
    result_provenance: trust.resultProvenance || null,
    effective_citeable: trust.citeable,
    gate_reason: trust.gateReason,
    expected_provenance: trust.expectedProvenance || null,
    content_id: value.content_id || null,
    event_id: value.event_id || null,
    task_id: value.task_id || null,
    model: value.model || null,
    creator_ref: value.creator_ref || null,
    verified: typeof value.verified === 'boolean' ? value.verified : null,
    bit_accuracy: value.bit_accuracy == null ? null : value.bit_accuracy,
    success_threshold: value.success_threshold == null ? null : value.success_threshold,
    evidence_status: value.evidence_status || null,
    evidence_signature: value.evidence_signature || null,
    original_sha256: value.original_sha256 || null,
    protected_sha256: value.protected_sha256 || null,
    observed_sha256: value.observed_sha256 || null,
  };
}

function resultMetadata(result) {
  const value = Object.assign({}, result || {});
  delete value.artifacts_b64;
  if (value.protected_image) {
    value.protected_image = { url: value.protected_image.url || '' };
  }
  return value;
}

Page({
  data: {
    navs: NAVS, rotIdx: 0, rot: 0, showSplash: false,
    health: 'syncing', healthText: '…', apiConfigError: '', steps: STEPS,
    models: MODEL_ORDER.map((name) => ({ name, provenanceReady: false, shortReason: '状态核验中' })), attacks: ATTACKS,
    model: '', modelReady: false, modelStatusText: '正在核验 checkpoint 登记、校准与签名清单', modelStatusClass: 'warn',
    attack: 'jpeg50', imgPath: '', loading: false, loadingAction: '', step: 1,
    creatorRef: '', contentId: '', verifyImgPath: '', verifyImageGenerated: false, verifyUploadConsent: false,
    result: null, resultScenario: '', resultTitle: '', resultNote: '', imgs: [], showMetrics: false,
    metricPrimaryLabel: 'Bit Accuracy', metricSecondaryLabel: 'PSNR',
    accText: '—', accClass: 'muted', psnrText: '—', verdict: null,
    modeText: '', modeClass: 'warn', provenanceText: '', gateReasonText: '',
    claimText: '', claimClass: 'risk', claimValid: false, declaredClaimValid: false, taskId: '',
    uploadConsent: false, isBuiltInSample: false,
    evidenceText: '', showEvidence: false, posterPath: '', error: '', localArtifactError: '', scrollTo: '',
    sigOk: false, sigText: '连接中', fp: '', blocking: 0, findings: [], demoReady: false, claimsReady: false, auditErr: '',
    user: { avatar: '', nick: '' }, list: [], editing: false,
    needLogin: false, tmpAvatar: '', tmpNick: '',
    cFiles: [], cLoading: false, cSum: null, cRows: [], cModel: 'SepMark',
    wmModels: [
      { n: 'LIDMark', d: '第三方底层模型 · 项目负责协议适配、评测与证据验链', t: '第三方模型' },
      { n: 'KAD-Net', d: '第三方底层模型 · 项目负责可信注册、校准与系统集成', t: '第三方模型' },
      { n: 'WaveGuard', d: '第三方底层模型 · 项目负责统一攻击协议与基线复核', t: '第三方模型' },
      { n: 'SepMark', d: '第三方底层模型 · 项目负责统一适配、负控制与证据门禁', t: '第三方模型' },
    ],
    regs: [
      { c: '第六条', d: '隐式标识方向的技术对应探索' },
      { c: '第七条', d: '抗干扰能力需以正式基准报告证明' },
      { c: '第八条', d: '为授权查验流程提供技术接口' },
      { c: '第十二条', d: '内容可信体系的研究型实现' },
    ],
  },

  onLoad() {
    const app = getApp();
    if (app && app.globalData && !app.globalData.splashShown) this.setData({ showSplash: true });
    const user = wx.getStorageSync('jys_user') || { avatar: '', nick: '' };
    if (!user.avatar || !user.nick) {
      this.setData({ needLogin: true, tmpAvatar: user.avatar || '', tmpNick: user.nick || '' });
    } else {
      this.setData({ user, creatorRef: user.nick });
    }
    this.checkHealth();
    this.loadAudit();
  },

  onObAvatar(event) {
    const url = event.detail.avatarUrl;
    wx.getFileSystemManager().saveFile({
      tempFilePath: url,
      success: (result) => this.setData({ tmpAvatar: result.savedFilePath }),
      fail: () => this.setData({ tmpAvatar: url }),
    });
  },
  onObNick(event) { this.setData({ tmpNick: event.detail.value }); },
  obSubmit() {
    if (!this.data.tmpAvatar || !this.data.tmpNick) {
      wx.showToast({ title: '请设置头像和昵称', icon: 'none' }); return;
    }
    const user = { avatar: this.data.tmpAvatar, nick: this.data.tmpNick };
    wx.setStorageSync('jys_user', user);
    this.setData({ user, creatorRef: user.nick, needLogin: false, rotIdx: 0, rot: 0 });
  },
  onShow() {
    const user = wx.getStorageSync('jys_user') || { avatar: '', nick: '' };
    const next = { user };
    if (!this.data.creatorRef && user.nick) next.creatorRef = user.nick;
    this.setData(next);
    this.refreshHistory();
    this.loadModelStatus();
  },
  onUnload() { removeGeneratedProtected(this.data.verifyImageGenerated ? this.data.verifyImgPath : ''); },

  switchFace(event) {
    const idx = Number(event.currentTarget.dataset.i);
    this.setData({ rotIdx: idx, rot: -idx * 90 });
  },
  onSplashDone() {
    const app = getApp();
    if (app && app.globalData) app.globalData.splashShown = true;
    this.setData({ showSplash: false });
  },
  onTap(event) {
    const fx = this.selectComponent('#tapfx');
    if (fx && event && event.detail && event.detail.x != null) fx.burst(event.detail.x, event.detail.y);
  },

  checkHealth() {
    const cfg = apiConfigStatus();
    if (!cfg.ok) {
      this.setData({ health: 'bad', healthText: '未配置', apiConfigError: cfg.message }); return;
    }
    request('/api/health')
      .then((value) => this.setData({
        health: value && value.ok ? 'ok' : 'bad',
        healthText: value && value.ok ? '在线' : '异常',
        apiConfigError: '',
      }))
      .catch((error) => this.setData({ health: 'bad', healthText: '离线', apiConfigError: fmtErr(error) }));
  },
  loadModelStatus() {
    request('/api/models/status').then((payload) => {
      const validated = validateModelStatus(payload);
      const current = validated.options.find((item) => item.name === this.data.model && item.provenanceReady);
      const model = current ? current.name : (validated.preferredModel || '');
      const blocked = validated.options
        .filter((item) => !item.provenanceReady)
        .map((item) => item.name + '：' + item.reason)
        .join('；');
      this.setData({
        models: validated.options,
        model,
        modelReady: !!model,
        modelStatusText: model
          ? '默认 ' + model + ' · registered + calibrated + trusted；禁用项：' + (blocked || '无')
          : '不可保护：无 provenance-ready 模型 · ' + blocked,
        modelStatusClass: model ? 'safe' : 'risk',
      });
    }).catch((error) => this.setData({
      models: MODEL_ORDER.map((name) => ({ name, provenanceReady: false, shortReason: '状态不可验证' })),
      model: '',
      modelReady: false,
      modelStatusText: '不可保护：' + fmtErr(error),
      modelStatusClass: 'risk',
    }));
  },
  onSelectModel(event) {
    const model = event.currentTarget.dataset.v;
    const option = this.data.models.find((item) => item.name === model);
    if (!option || !option.provenanceReady) {
      wx.showToast({ title: (option && option.reason) || '模型未通过可信门禁', icon: 'none' }); return;
    }
    this.setData({ model, modelReady: true });
  },
  onSelectAttack(event) { this.setData({ attack: event.currentTarget.dataset.v }); },
  onCreatorRef(event) { this.setData({ creatorRef: event.detail.value }); },
  onContentId(event) { this.setData({ contentId: String(event.detail.value || '').trim().toLowerCase() }); },
  chooseImage() {
    wx.chooseMedia({
      count: 1, mediaType: ['image'], sourceType: ['album', 'camera'], sizeType: ['compressed'],
      success: (result) => {
        removeGeneratedProtected(this.data.verifyImageGenerated ? this.data.verifyImgPath : '');
        this.setData({
          imgPath: result.tempFiles[0].tempFilePath,
          contentId: '', verifyImgPath: '', verifyImageGenerated: false,
          result: null, error: '', localArtifactError: '',
          step: 1, uploadConsent: false, verifyUploadConsent: false, isBuiltInSample: false,
        });
      },
    });
  },
  chooseVerifyImage() {
    wx.chooseMedia({
      count: 1, mediaType: ['image'], sourceType: ['album', 'camera'], sizeType: ['original'],
      success: (result) => {
        removeGeneratedProtected(this.data.verifyImageGenerated ? this.data.verifyImgPath : '');
        this.setData({
          verifyImgPath: result.tempFiles[0].tempFilePath,
          verifyImageGenerated: false, verifyUploadConsent: false, error: '', step: 3,
        });
      },
    });
  },
  onUploadConsent(event) {
    this.setData({ uploadConsent: (event.detail.value || []).indexOf('accepted') !== -1 });
  },
  onVerifyUploadConsent(event) {
    this.setData({ verifyUploadConsent: (event.detail.value || []).indexOf('accepted') !== -1 });
  },
  useSample() {
    wx.showLoading({ title: '载入样本…' });
    request('/api/samples').then((list) => {
      const sample = Array.isArray(list) && list[0];
      if (!sample) throw { message: '无内置样本' };
      return new Promise((resolve, reject) => wx.downloadFile({
        url: buildApiUrl('/api/samples/' + encodeURIComponent(sample.id) + '/image'),
        header: apiHeaders(),
        success: (result) => (result.statusCode === 200 ? resolve(result.tempFilePath) : reject({ message: '样本下载失败' })),
        fail: reject,
      }));
    }).then((tempPath) => {
      wx.hideLoading();
      removeGeneratedProtected(this.data.verifyImageGenerated ? this.data.verifyImgPath : '');
      this.setData({
        imgPath: tempPath, contentId: '', verifyImgPath: '', verifyImageGenerated: false,
        result: null, error: '', localArtifactError: '',
        step: 1, uploadConsent: false, verifyUploadConsent: false, isBuiltInSample: true,
      });
    }).catch((error) => {
      wx.hideLoading(); wx.showToast({ title: fmtErr(error), icon: 'none' });
    });
  },
  canUploadPrimary() {
    if (!this.data.imgPath) { wx.showToast({ title: '请先选择图片', icon: 'none' }); return false; }
    if (!this.data.isBuiltInSample && !this.data.uploadConsent) {
      wx.showModal({ title: '请先确认上传用途', content: '请阅读并勾选图片上传与服务端处理提示。', showCancel: false });
      return false;
    }
    return true;
  },

  protectContent() {
    if (!this.data.modelReady || !this.data.model) {
      wx.showModal({ title: '模型不可发布', content: this.data.modelStatusText, showCancel: false }); return;
    }
    if (!this.canUploadPrimary()) return;
    const creatorRef = String(this.data.creatorRef || '').trim();
    if (!creatorRef || creatorRef.length > 128) {
      wx.showToast({ title: '请填写 1–128 字符的创作者标识', icon: 'none' }); return;
    }
    this.setData({ loading: true, loadingAction: 'protect', error: '', localArtifactError: '', result: null, step: 2, scrollTo: '' });
    uploadFile('/api/provenance/protect', this.data.imgPath, { creator_ref: creatorRef, model: this.data.model })
      .then((result) => {
        const protectedImage = result.protected_image || {};
        return writeProtectedPng(protectedImage.png_base64, result.content_id)
          .then((path) => ({ result, path, localError: '' }))
          .catch(() => ({ result, path: '', localError: '保护图已由后端生成，但写入本地核验文件失败；可从相册另选传播图。' }));
      })
      .then(({ result, path, localError }) => {
        if (this.data.verifyImageGenerated && this.data.verifyImgPath !== path) {
          removeGeneratedProtected(this.data.verifyImgPath);
        }
        this.setData({
          contentId: result.content_id || '',
          verifyImgPath: path,
          verifyImageGenerated: !!path,
          verifyUploadConsent: !!path,
          localArtifactError: localError,
          step: 2,
        });
        this.renderProvenanceResult(result, 'protect', path);
      })
      .catch((error) => this.setData({ loading: false, loadingAction: '', error: fmtErr(error), step: 1 }));
  },

  verifyContent() {
    const contentId = String(this.data.contentId || '').trim().toLowerCase();
    if (!/^[a-f0-9]{32}$/.test(contentId)) {
      wx.showToast({ title: '请输入 32 位登记内容 ID', icon: 'none' }); return;
    }
    if (!this.data.verifyImgPath) {
      wx.showToast({ title: '请选择待核验的传播图片', icon: 'none' }); return;
    }
    if (!this.data.verifyUploadConsent) {
      wx.showModal({ title: '请先确认上传用途', content: '请确认拥有待核验图片的处理权限。', showCancel: false });
      return;
    }
    this.setData({ loading: true, loadingAction: 'verify', error: '', result: null, step: 4, scrollTo: '' });
    uploadFile('/api/provenance/verify', this.data.verifyImgPath, { content_id: contentId })
      .then((result) => this.renderProvenanceResult(result, 'verify'))
      .catch((error) => this.setData({ loading: false, loadingAction: '', error: fmtErr(error), step: 3 }));
  },

  runInfer() {
    if (!this.canUploadPrimary()) return;
    this.setData({ loading: true, loadingAction: 'infer', error: '', result: null, step: 1, scrollTo: '' });
    uploadFile('/api/infer/single', this.data.imgPath, {
      model: this.data.model, attack: this.data.attack, return_b64: 'true',
    }).then((result) => this.renderInferenceResult(result))
      .catch((error) => this.setData({ loading: false, loadingAction: '', error: fmtErr(error), step: 1 }));
  },

  renderInferenceResult(result) {
    const b64 = result.artifacts_b64 || {};
    const imgs = ['original', 'watermarked', 'attacked', 'heatmap']
      .filter((key) => b64[key])
      .map((key) => ({ key, label: IMG_LABELS[key], src: 'data:image/png;base64,' + b64[key] }));
    const metrics = result.metrics || {};
    const accuracy = pickAcc(metrics);
    const trust = resultTrust(result, 'infer_single');
    const verdict = { cls: 'risk', text: '单样本工程评估 · 不可引用' };
    const evidence = provenanceEvidence(result, trust, 'infer_single');
    evidence.metrics = metrics;
    evidence.warnings = result.warnings || [];
    this.setData({
      loading: false, loadingAction: '', step: 1, result: resultMetadata(result), resultScenario: 'infer_single',
      resultTitle: '模型评估结果（不可作来源结论）',
      resultNote: '本结果仅说明一次“嵌入→攻击模拟→解码”的工程表现；即使执行真实检查点，也不得用于证明既有图片来源、平台合规或司法取证。',
      imgs, showMetrics: true, metricPrimaryLabel: '单样本 Bit Accuracy', metricSecondaryLabel: 'PSNR',
      accText: pct(accuracy), accClass: scoreClass(accuracy),
      psnrText: metrics.psnr != null ? fixed(metrics.psnr) + ' dB' : '—', verdict,
      modeText: trust.modeText, modeClass: trust.modeClass, provenanceText: trust.provenanceText,
      gateReasonText: trust.gateReasonText, claimText: trust.claimText, claimClass: trust.claimClass,
      claimValid: trust.citeable, declaredClaimValid: trust.declaredClaimValid, taskId: result.task_id || '',
      evidenceText: JSON.stringify(evidence, null, 2), posterPath: '', showEvidence: false,
    });
    setTimeout(() => this.setData({ scrollTo: 'resultCard' }), 60);
    history.add({
      imgPath: this.data.imgPath, model: result.model, attack: result.attack,
      accText: pct(accuracy), accClass: scoreClass(accuracy), scenario: 'infer_single', payload: result,
    }).then(() => this.refreshHistory());
  },

  renderProvenanceResult(result, scenario, localProtectedPath) {
    const trust = resultTrust(result, scenario);
    const imgs = localProtectedPath
      ? [{ key: 'protected', label: IMG_LABELS.protected, src: localProtectedPath }]
      : [];
    const accuracy = scenario === 'verify' ? result.bit_accuracy : null;
    let verdict;
    if (scenario === 'protect') {
      verdict = trust.citeable
        ? { cls: 'ok', text: '保护登记已签名绑定 · 可引用' }
        : { cls: 'risk', text: '保护记录已创建 · 当前不可引用' };
    } else if (trust.citeable) {
      verdict = result.verified === true
        ? { cls: 'ok', text: '登记水印匹配 · 结果可引用' }
        : { cls: 'warn', text: '登记水印未通过 · 结果可引用' };
    } else {
      verdict = { cls: 'risk', text: '核验响应未通过可信门禁 · 不可引用' };
    }
    const note = trust.citeable
      ? '该结果只可引用为本次已登记保护/核验事件的技术记录；签名与模型绑定不自动等同于司法采信、监管认定或平台合规。'
      : '本响应未同时满足 real_checkpoint、claim_valid=true 与场景对应的登记来源，禁止作来源、合规或取证结论。';
    this.setData({
      loading: false, loadingAction: '', step: scenario === 'protect' ? 2 : 5,
      result: resultMetadata(result), resultScenario: scenario,
      resultTitle: scenario === 'protect' ? '来源保护登记结果' : '登记来源核验结果',
      resultNote: note, imgs, showMetrics: scenario === 'verify',
      metricPrimaryLabel: '核验 Bit Accuracy', metricSecondaryLabel: '通过阈值',
      accText: accuracy == null ? '—' : pct(accuracy), accClass: scoreClass(accuracy),
      psnrText: result.success_threshold == null ? '—' : pct(result.success_threshold), verdict,
      modeText: trust.modeText, modeClass: trust.modeClass, provenanceText: trust.provenanceText,
      gateReasonText: trust.gateReasonText, claimText: trust.claimText, claimClass: trust.claimClass,
      claimValid: trust.citeable, declaredClaimValid: trust.declaredClaimValid,
      taskId: result.event_id || result.content_id || '',
      evidenceText: JSON.stringify(provenanceEvidence(result, trust, scenario), null, 2),
      posterPath: '', showEvidence: false,
    });
    setTimeout(() => this.setData({ scrollTo: 'resultCard' }), 60);
    history.add({
      imgPath: scenario === 'verify' ? this.data.verifyImgPath : this.data.imgPath,
      model: result.model, attack: scenario === 'protect' ? '保护登记' : '登记核验',
      accText: accuracy == null ? '—' : pct(accuracy), accClass: scoreClass(accuracy),
      scenario, payload: result,
    }).then(() => this.refreshHistory());
  },

  toggleEvidence() { this.setData({ showEvidence: !this.data.showEvidence }); },
  reset() {
    removeGeneratedProtected(this.data.verifyImageGenerated ? this.data.verifyImgPath : '');
    this.setData({
      result: null, resultScenario: '', imgPath: '', contentId: '', verifyImgPath: '', verifyImageGenerated: false,
      step: 1, error: '', localArtifactError: '', showEvidence: false, posterPath: '',
      uploadConsent: false, verifyUploadConsent: false, isBuiltInSample: false,
    });
  },
  goMea() { wx.navigateTo({ url: '/pages/mea/index' }); },
  goCompliance() { this.setData({ rotIdx: 1, rot: -90 }); },

  cSelModel(event) { this.setData({ cModel: event.currentTarget.dataset.v }); },
  cChoose() {
    wx.chooseMedia({
      count: 9, mediaType: ['image'], sourceType: ['album'], sizeType: ['compressed'],
      success: (result) => this.setData({ cFiles: result.tempFiles.map((file) => file.tempFilePath), cSum: null, cRows: [] }),
    });
  },
  cRun() {
    const files = this.data.cFiles;
    if (!files.length) { wx.showToast({ title: '请先选择图片', icon: 'none' }); return; }
    // infer/single 不是既有图片盲检；能力上线前不上传、不计算、不猜测。
    const rows = files.map((src) => ({
      src, verdict: 'assessment_unavailable', accText: '未上传', cls: 'risk', label: '不可判定',
    }));
    this.setData({
      cLoading: false, cRows: rows,
      cSum: {
        total: rows.length, assessed: 0, unavailable: rows.length, rate: '不可判定',
        modeText: 'UNAVAILABLE · 盲检能力未实现',
        claimText: 'CLAIM INVALID · 未产生合规结论',
      },
    });
    wx.showModal({
      title: '当前不可判定',
      content: '当前后端仅支持嵌入后解码评估，不具备对既有图片的通用盲检能力。本次所选图片未上传。',
      showCancel: false,
    });
  },
  onShareAppMessage() { return { title: '寻源路 · 已登记内容来源核验演示', path: '/pages/home/index' }; },

  loadAudit() {
    request('/api/evidence/audit').then((audit) => {
      const signature = audit.signature || {};
      this.setData({
        sigOk: !!signature.verified,
        sigText: signature.verified ? 'Ed25519 已验签' : (signature.status || '未生成'),
        fp: (signature.public_key_fingerprint_sha256 || '').slice(0, 24),
        blocking: (audit.blocking_findings || []).length,
        findings: (audit.findings || []).map((finding) => ({ code: finding.code, msg: finding.message, sev: finding.severity })),
        demoReady: !!audit.ready_for_demo, claimsReady: !!audit.ready_for_claims, auditErr: '',
      });
    }).catch((error) => this.setData({ auditErr: fmtErr(error), sigText: '不可用' }));
  },

  refreshHistory() {
    const raw = history.load();
    this.setData({ list: raw.map((value) => Object.assign({}, value, {
      timeText: ts(value.t),
      contentIdText: value.contentId ? value.contentId.slice(0, 10) + '…' : '',
    })) });
  },
  onChooseAvatar(event) {
    const url = event.detail.avatarUrl;
    const save = (path) => {
      const user = Object.assign({}, this.data.user, { avatar: path });
      this.setData({ user }); wx.setStorageSync('jys_user', user);
    };
    wx.getFileSystemManager().saveFile({
      tempFilePath: url,
      success: (result) => save(result.savedFilePath),
      fail: () => save(url),
    });
  },
  startEdit() { this.setData({ editing: true }); },
  onNick(event) {
    const user = Object.assign({}, this.data.user, { nick: event.detail.value });
    this.setData({ user, editing: false }); wx.setStorageSync('jys_user', user);
  },
  clearHistory() {
    wx.showModal({
      title: '清空历史', content: '确定清空全部本地任务记录？',
      success: (modal) => { if (modal.confirm) { history.clear(); this.refreshHistory(); } },
    });
  },

  saveProtectedImage() {
    if (!this.data.verifyImageGenerated || !this.data.verifyImgPath) return;
    wx.saveImageToPhotosAlbum({
      filePath: this.data.verifyImgPath,
      success: () => wx.showToast({ title: '保护图已保存' }),
      fail: (error) => {
        if (/deny|authorize|auth/.test((error && error.errMsg) || '')) {
          wx.showModal({
            title: '需要相册权限', content: '请在设置中允许“保存到相册”',
            success: (modal) => { if (modal.confirm) wx.openSetting(); },
          });
        } else wx.showToast({ title: '保存失败', icon: 'none' });
      },
    });
  },

  generatePoster() {
    const result = this.data.result;
    if (!result) return;
    wx.showLoading({ title: '生成中…' });
    wx.createSelectorQuery().in(this).select('#posterCanvas').fields({ node: true, size: true }).exec((response) => {
      if (!response || !response[0] || !response[0].node) {
        wx.hideLoading(); wx.showToast({ title: '画布未就绪', icon: 'none' }); return;
      }
      const canvas = response[0].node;
      const ctx = canvas.getContext('2d');
      const info = (wx.getWindowInfo && wx.getWindowInfo()) || wx.getSystemInfoSync();
      const dpr = (info && info.pixelRatio) || 2;
      const width = 600; const height = 920;
      canvas.width = width * dpr; canvas.height = height * dpr; ctx.scale(dpr, dpr);
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = '#0369a1'; ctx.fillRect(0, 0, width, 10);
      ctx.textAlign = 'left'; ctx.fillStyle = '#0b2a45'; ctx.font = 'bold 46px sans-serif'; ctx.fillText('寻源路', 44, 100);
      ctx.fillStyle = '#5a6b81'; ctx.font = '24px sans-serif'; ctx.fillText('已登记内容来源核验 · 技术记录卡', 44, 140);
      const panelY = 200;
      ctx.strokeStyle = '#e3eaf3'; ctx.lineWidth = 2; ctx.strokeRect(44, panelY, width - 88, 270);
      ctx.fillStyle = '#5a6b81'; ctx.font = '24px sans-serif';
      ctx.fillText(this.data.showMetrics ? this.data.metricPrimaryLabel : '结果场景', 76, panelY + 56);
      ctx.fillStyle = '#0369a1'; ctx.font = this.data.showMetrics ? 'bold 88px sans-serif' : 'bold 34px sans-serif';
      ctx.fillText(this.data.showMetrics ? this.data.accText : (this.data.resultTitle || '-').slice(0, 18), 72, panelY + 155);
      ctx.fillStyle = '#0b2a45'; ctx.font = '26px sans-serif';
      ctx.fillText(((this.data.verdict && this.data.verdict.text) || '').slice(0, 25), 76, panelY + 225);
      ctx.fillStyle = '#5a6b81'; ctx.font = '22px sans-serif';
      ctx.fillText('模型 ' + (result.model || '-'), 44, 550);
      ctx.fillText('模式 ' + (result.mode || '-'), 44, 590);
      ctx.fillText('来源 ' + String(result.result_provenance || '-').slice(0, 36), 44, 630);
      ctx.fillText('记录 ' + String(result.event_id || result.content_id || result.task_id || '-').slice(0, 36), 44, 670);
      ctx.fillText('后端 claim_valid ' + (this.data.declaredClaimValid ? 'TRUE' : 'FALSE'), 44, 710);
      ctx.fillStyle = this.data.claimValid ? '#0369a1' : '#dc2626'; ctx.font = 'bold 22px sans-serif';
      ctx.fillText(this.data.claimValid ? '三元可信门禁通过 · 本事件结果可引用' : '可信门禁未通过 · 禁止作来源/合规/取证结论', 44, 842);
      ctx.fillStyle = '#93a3b8'; ctx.font = '19px sans-serif';
      ctx.fillText('签名完整性不自动等同司法采信或监管认定', 44, 880);
      wx.canvasToTempFilePath({
        canvas,
        success: (output) => { this.setData({ posterPath: output.tempFilePath }); wx.hideLoading(); },
        fail: () => { wx.hideLoading(); wx.showToast({ title: '生成失败', icon: 'none' }); },
      });
    });
  },
  savePoster() {
    if (!this.data.posterPath) return;
    wx.saveImageToPhotosAlbum({
      filePath: this.data.posterPath,
      success: () => wx.showToast({ title: '已保存到相册' }),
      fail: (error) => {
        if (/deny|authorize|auth/.test((error && error.errMsg) || '')) {
          wx.showModal({
            title: '需要相册权限', content: '请在设置中允许“保存到相册”',
            success: (modal) => { if (modal.confirm) wx.openSetting(); },
          });
        } else wx.showToast({ title: '保存失败', icon: 'none' });
      },
    });
  },
});
