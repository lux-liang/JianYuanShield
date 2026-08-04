const { request, uploadFile, fmtErr } = require('../../utils/request');
const { apiConfigStatus } = require('../../utils/config');
const { resultTrust } = require('../../utils/trust');
const { pct, scoreClass, fixed, pickAcc } = require('../../utils/format');

const MODELS = ['LIDMark', 'KAD-Net', 'SepMark', 'WaveGuard'];
const POLICY_PROFILES = [
  { v: 'balanced', t: '均衡', risk: 0.6, fidelity: 0.2, minimum: 0.45 },
  { v: 'security', t: '安全优先', risk: 0.9, fidelity: 0.1, minimum: 0.70 },
  { v: 'quality', t: '质量优先', risk: 0.4, fidelity: 0.45, minimum: 0.45 },
];
const INTERACTION_TEXT = {
  coexistence: { t: '共存风险观测', cls: 'ok' },
  source_dominant: { t: '来源占优', cls: 'warn' },
  source_overwritten: { t: '来源被覆盖', cls: 'risk' },
  destructive_collision: { t: '破坏性冲突', cls: 'risk' },
};
const ATTACKS = [
  { v: 'jpeg50', t: 'JPEG50' },
  { v: 'jpeg70', t: 'JPEG70' },
  { v: 'resize', t: '缩放' },
  { v: 'noise', t: '噪声' },
  { v: 'clean', t: '无攻击' },
];
const IMG_LABELS = { watermarked: '含水印', attacked: '被攻击', heatmap: '热力图' };

function assertPolicyResponse(result, requestedThreats, requestedProfile) {
  const evidence = result && result.evidence;
  const signature = evidence && evidence.release_signature;
  const recommendation = result && result.recommendation;
  const ranking = result && result.ranking;
  const interactions = result && result.interaction_plan;
  const requestEcho = result && result.request;
  const expectedThreatModels = (requestedThreats || []).map((item) => item.model).sort();
  const echoedThreatModels = Object.keys((requestEcho && requestEcho.threat_probabilities) || {}).sort();
  const expectedProbability = requestedThreats && requestedThreats.length
    ? 1 / requestedThreats.length : 0;
  const isHash = (value) => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
  const unit = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  const rankingModels = new Set((ranking || []).map((item) => item && item.model));
  const rankingValid = (ranking || []).every((item) => item
    && MODELS.indexOf(item.model) !== -1
    && typeof item.feasible === 'boolean'
    && typeof item.pareto_optimal === 'boolean'
    && unit(item.score)
    && unit(item.expected_source_protocol_normalized_margin_cluster_lcb)
    && unit(item.worst_case_source_protocol_normalized_margin_cluster_lcb)
    && unit(item.worst_case_source_protocol_success_rate_cluster_lcb)
    && Array.isArray(item.constraint_violations));
  const scoring = result && result.scoring;
  const stability = scoring && scoring.selection_stability;
  const familyMetrics = [
    'source_protocol_normalized_margin', 'source_protocol_success',
    'attacker_protocol_normalized_margin', 'attacker_protocol_success',
    'second_vs_original_psnr', 'second_vs_original_ssim',
  ];
  const semantics = scoring && scoring.model_semantics;
  const frequencies = stability && stability.selection_frequency;
  const ablation = result && result.ablation;
  const legacyAblation = ablation && ablation.legacy_iid_raw_accuracy;
  const probabilityTotal = Object.values((requestEcho && requestEcho.threat_probabilities) || {})
    .reduce((sum, value) => sum + value, 0);
  const frequencyKeys = frequencies ? Object.keys(frequencies).sort() : [];
  const frequencyTotal = frequencies
    ? Object.values(frequencies).reduce((sum, value) => sum + value, 0) : NaN;
  if (!result || result.schema_version !== 'collaboration-recommendation.v2'
      || !Array.isArray(ranking) || ranking.length !== 4
      || rankingModels.size !== 4 || !rankingValid
      || JSON.stringify(echoedThreatModels) !== JSON.stringify(expectedThreatModels)
      || Math.abs(probabilityTotal - 1) > 1e-7
      || echoedThreatModels.some((model) => Math.abs(
        requestEcho.threat_probabilities[model] - expectedProbability
      ) > 1e-7)
      || !MODELS.every((model, index) => requestEcho
        && requestEcho.candidate_models && requestEcho.candidate_models[index] === model)
      || requestEcho.risk_aversion !== requestedProfile.risk
      || requestEcho.fidelity_weight !== requestedProfile.fidelity
      || requestEcho.minimum_worst_case_protocol_normalized_margin !== requestedProfile.minimum
      || !evidence || evidence.content_verified !== true
      || evidence.signature_verified !== true || evidence.signer_pinned !== true
      || evidence.rows !== 4096 || evidence.cells !== 16 || evidence.images_per_cell !== 256
      || evidence.image_count !== 256 || evidence.identity_count !== 217
      || evidence.repeated_identity_count !== 24
      || evidence.images_in_repeated_identities !== 63 || evidence.max_cluster_size !== 10
      || !scoring || scoring.uncertainty_method !== 'deterministic_identity_cluster_bootstrap_percentile'
      || scoring.estimand !== 'equal_identity_weighted_mean_of_within_identity_image_means'
      || scoring.raw_bit_accuracy_use !== 'diagnostic_only_not_cross_model_ranked'
      || scoring.bootstrap_rng !== 'numpy_pcg64_multinomial'
      || scoring.bootstrap_seed !== 20260603 || scoring.bootstrap_resamples !== 20000
      || scoring.multiplicity_adjustment !== 'bonferroni_one_sided_fixed_full_selection_family'
      || scoring.family_size !== 96 || scoring.identity_count !== 217
      || JSON.stringify(scoring.family_metrics) !== JSON.stringify(familyMetrics)
      || Math.abs(scoring.per_comparison_alpha - (0.05 / 96)) > 5e-8
      || !semantics
      || semantics.LIDMark.message_length !== 16 || semantics.LIDMark.primary_decoder !== 'FHD_id_head'
      || semantics['KAD-Net'].message_length !== 30 || semantics['KAD-Net'].primary_decoder !== 'ST_Decoder_C'
      || semantics.SepMark.message_length !== 128 || semantics.SepMark.primary_decoder !== 'decoder_C'
      || semantics.WaveGuard.message_length !== 30 || semantics.WaveGuard.primary_decoder !== 'tracer'
      || MODELS.some((model) => semantics[model].success_threshold !== 0.9)
      || !stability || stability.method !== 'cluster_resample_point_policy_selection_frequency'
      || stability.resamples !== 20000 || !unit(stability.selected_model_frequency)
      || JSON.stringify(frequencyKeys) !== JSON.stringify(['KAD-Net', 'LIDMark', 'SepMark', 'WaveGuard', 'none'])
      || Object.values(frequencies || {}).some((value) => !unit(value))
      || Math.abs(frequencyTotal - 1) > 1e-6
      || !legacyAblation
      || legacyAblation.method !== 'legacy_raw_bit_accuracy_iid_normal_wilson_diagnostic_only'
      || !isHash(evidence.summary_sha256) || !isHash(evidence.policy_sha256)
      || !isHash(evidence.protocol_sha256)
      || !signature || signature.verified !== true || signature.signer_pinned !== true
      || ['release-core', 'release'].indexOf(signature.profile) === -1
      || !isHash(signature.manifest_sha256)
      || !isHash(signature.public_key_fingerprint_sha256)
      || signature.policy_sha256 !== evidence.policy_sha256) {
    throw { code: 'untrusted_policy_response', message: '协同响应未通过 release-core 证据契约校验' };
  }
  if (result.status === 'constraint_unsatisfied' && recommendation === null) {
    throw { code: 'constraint_unsatisfied', message: '当前硬约束下不存在可选模型' };
  }
  const attackerModels = new Set((interactions || []).map((item) => item && item.attacker_model));
  if (result.status !== 'recommendation_ready' || !recommendation
      || recommendation.feasible !== true || recommendation.pareto_optimal !== true
      || !unit(recommendation.expected_source_protocol_normalized_margin_cluster_lcb)
      || !unit(recommendation.worst_case_source_protocol_normalized_margin_cluster_lcb)
      || ranking[0].model !== recommendation.model
      || ablation.identity_cluster_normalized_policy_selected_model !== recommendation.model
      || ablation.selection_changed !== (legacyAblation.selected_model !== recommendation.model)
      || Math.abs(stability.selected_model_frequency - frequencies[recommendation.model]) > 5e-8
      || !Array.isArray(recommendation.low_risk_interaction_models)
      || !Array.isArray(interactions) || interactions.length !== 4
      || attackerModels.size !== 4
      || !interactions.every((item) => item && item.source_model === recommendation.model
        && MODELS.indexOf(item.attacker_model) !== -1
        && /^planned_/.test(item.policy_hint || '')
        && unit(item.source_protocol_normalized_margin_cluster_lcb)
        && unit(item.attacker_protocol_normalized_margin_cluster_lcb))) {
    throw { code: 'invalid_policy_response', message: '协同推荐结构不满足可执行契约' };
  }
  return result;
}

Page({
  data: {
    attacks: ATTACKS, attack: 'jpeg50', imgPath: '', loading: false, cards: [], error: '', uploadConsent: false,
    policyProfiles: POLICY_PROFILES, policyProfile: 'balanced',
    threatModels: MODELS.map((model) => ({ model, selected: true })),
    policyLoading: false, policyError: '', policyResult: null,
  },

  onToggleThreat(e) {
    const model = e.currentTarget.dataset.model;
    const selected = this.data.threatModels.filter((item) => item.selected).length;
    const next = this.data.threatModels.map((item) => {
      if (item.model !== model) return item;
      if (item.selected && selected === 1) return item;
      return Object.assign({}, item, { selected: !item.selected });
    });
    this.setData({ threatModels: next, policyResult: null, policyError: '' });
  },

  onSelectPolicyProfile(e) {
    this.setData({ policyProfile: e.currentTarget.dataset.v, policyResult: null, policyError: '' });
  },

  runPolicy() {
    const cfg = apiConfigStatus();
    if (!cfg.ok) { this.setData({ policyError: cfg.message, policyResult: null }); return; }
    const profile = POLICY_PROFILES.find((item) => item.v === this.data.policyProfile) || POLICY_PROFILES[0];
    const threats = this.data.threatModels
      .filter((item) => item.selected)
      .map((item) => ({ model: item.model, exposure: 1.0 }));
    this.setData({ policyLoading: true, policyError: '', policyResult: null });
    request('/api/collaboration/recommend', {
      method: 'POST',
      data: {
        threats,
        candidate_models: MODELS,
        risk_aversion: profile.risk,
        fidelity_weight: profile.fidelity,
        minimum_worst_case_protocol_normalized_margin: profile.minimum,
      },
    }).then((payload) => {
      const result = assertPolicyResponse(payload, threats, profile);
      const recommendation = result.recommendation;
      const interactions = (result.interaction_plan || []).map((item) => {
        const meta = INTERACTION_TEXT[item.class] || { t: item.class || '未知', cls: 'risk' };
        return {
          model: item.attacker_model,
          label: meta.t,
          cls: meta.cls,
          sourceMargin: pct(item.source_protocol_normalized_margin_cluster_lcb),
          attackerMargin: pct(item.attacker_protocol_normalized_margin_cluster_lcb),
          action: 'PLANNED · ' + String(item.policy_hint || 'planned_block_second_embedding').replace(/_/g, ' '),
        };
      });
      const ranking = (result.ranking || []).map((item, index) => ({
        model: item.model,
        rank: index + 1,
        score: fixed(item.score, 3),
        expected: pct(item.expected_source_protocol_normalized_margin_cluster_lcb),
        worst: pct(item.worst_case_source_protocol_normalized_margin_cluster_lcb),
        feasible: item.feasible === true,
        pareto: item.pareto_optimal === true,
      }));
      const evidence = result.evidence || {};
      const releaseSignature = evidence.release_signature || {};
      this.setData({
        policyLoading: false,
        policyResult: {
          model: recommendation.model,
          score: fixed(recommendation.score, 3),
          expected: pct(recommendation.expected_source_protocol_normalized_margin_cluster_lcb),
          worst: pct(recommendation.worst_case_source_protocol_normalized_margin_cluster_lcb),
          initialPsnr: fixed(recommendation.initial_embedding_psnr_db, 2) + ' dB',
          postPsnr: fixed(recommendation.expected_post_attack_psnr_cluster_lcb_db, 2) + ' dB',
          compatible: (recommendation.low_risk_interaction_models || []).join('、') || '无',
          identityAudit: `${evidence.image_count} 图像 / ${evidence.identity_count} 身份 · 重复身份 ${evidence.repeated_identity_count} · 最大簇 ${evidence.max_cluster_size}`,
          bootstrapAudit: `${result.scoring.bootstrap_resamples} 次 · seed ${result.scoring.bootstrap_seed} · family ${result.scoring.family_size}`,
          stability: pct(result.scoring.selection_stability.selected_model_frequency),
          ablation: `${(result.ablation.legacy_iid_raw_accuracy.selected_model || 'none')} → ${(result.ablation.identity_cluster_normalized_policy_selected_model || 'none')} · changed=${result.ablation.selection_changed}`,
          ranking,
          interactions,
          rows: evidence.rows == null ? '—' : evidence.rows,
          cells: evidence.cells == null ? '—' : evidence.cells,
          summaryHash: evidence.summary_sha256 ? evidence.summary_sha256.slice(0, 12) + '…' : '—',
          policyHash: evidence.policy_sha256 ? evidence.policy_sha256.slice(0, 12) + '…' : '—',
          protocolHash: evidence.protocol_sha256 ? evidence.protocol_sha256.slice(0, 12) + '…' : '—',
          manifestHash: releaseSignature.manifest_sha256
            ? releaseSignature.manifest_sha256.slice(0, 12) + '…' : '—',
          signerFingerprint: releaseSignature.public_key_fingerprint_sha256
            ? releaseSignature.public_key_fingerprint_sha256.slice(0, 12) + '…' : '—',
        },
      });
    }).catch((error) => this.setData({
      policyLoading: false,
      policyResult: null,
      policyError: fmtErr(error),
    }));
  },

  chooseImage() {
    wx.chooseMedia({
      count: 1, mediaType: ['image'], sourceType: ['album', 'camera'], sizeType: ['compressed'],
      success: (r) => this.setData({ imgPath: r.tempFiles[0].tempFilePath, cards: [], error: '', uploadConsent: false }),
    });
  },
  onUploadConsent(e) { this.setData({ uploadConsent: (e.detail.value || []).indexOf('accepted') !== -1 }); },
  onSelectAttack(e) { this.setData({ attack: e.currentTarget.dataset.v }); },

  run() {
    if (!this.data.imgPath) { wx.showToast({ title: '请先选择图片', icon: 'none' }); return; }
    if (!this.data.uploadConsent) {
      wx.showModal({ title: '请先确认上传用途', content: '请阅读并勾选图片上传与服务端处理提示。', showCancel: false });
      return;
    }
    const cfg = apiConfigStatus();
    if (!cfg.ok) { this.setData({ error: cfg.message, cards: [] }); return; }
    this.setData({ loading: true, error: '', cards: [] });
    Promise.all(MODELS.map((model) =>
      uploadFile('/api/infer/single', this.data.imgPath, { model, attack: this.data.attack, return_b64: 'true' })
        .then((r) => {
          const b64 = r.artifacts_b64 || {};
          const m = r.metrics || {};
          const acc = pickAcc(m);
          // MEA 只调用 infer/single 做嵌入→攻击→解码工程评估，永不进入可引用场景。
          const trust = resultTrust(r, 'mea');
          return {
            model, acc: pct(acc), accClass: scoreClass(acc),
            psnr: m.psnr != null ? fixed(m.psnr) + ' dB' : '—',
            verdict: { cls: 'risk', t: '工程评估 · 不可引用' },
            modeText: trust.modeText,
            modeClass: trust.modeClass,
            provenanceText: trust.provenanceText,
            claimText: trust.claimText,
            claimClass: trust.claimClass,
            claimValid: trust.citeable,
            reason: (r.warnings || []).join('；'),
            imgs: ['watermarked', 'attacked', 'heatmap'].filter((k) => b64[k]).map((k) => ({ k, label: IMG_LABELS[k], src: 'data:image/png;base64,' + b64[k] })),
          };
        })
        .catch((e) => ({
          model, acc: '—', accClass: 'muted', psnr: '—',
          verdict: { cls: 'risk', t: '不可用' },
          modeText: 'UNAVAILABLE · 请求失败', modeClass: 'risk',
          provenanceText: 'UNTRUSTED · 未产生登记结果来源',
          claimText: 'CLAIM INVALID · 禁止作来源/合规/取证结论', claimClass: 'risk', claimValid: false,
          reason: fmtErr(e), imgs: [],
        }))
    )).then((cards) => this.setData({ loading: false, cards }))
      .catch((e) => this.setData({ loading: false, error: fmtErr(e) }));
  },

  onShareAppMessage() { return { title: '寻源路 · 多模型横评对比', path: '/pages/mea/index' }; },
});
