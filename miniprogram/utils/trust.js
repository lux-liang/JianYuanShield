// 结果可信门禁：任何调用方都必须声明业务场景，缺失场景一律 fail-closed。
const MODE = {
  real_checkpoint: { kind: 'real', text: 'REAL MODEL · 已执行真实检查点', cls: 'info' },
  demo_simulation: { kind: 'simulation', text: 'SIMULATION · 演示模拟', cls: 'warn' },
  capability_unavailable: { kind: 'unavailable', text: 'UNAVAILABLE · 能力不可用', cls: 'risk' },
  unavailable: { kind: 'unavailable', text: 'UNAVAILABLE · 能力不可用', cls: 'risk' },
};

const PROVENANCE = {
  registered_protection_record: {
    scenario: 'protect',
    text: 'REGISTERED · 已登记来源保护记录',
  },
  registered_blind_verification: {
    scenario: 'verify',
    text: 'VERIFIED · 已登记来源盲核验',
  },
};

const EXPECTED_PROVENANCE = {
  protect: 'registered_protection_record',
  verify: 'registered_blind_verification',
};

const SCENARIO_TEXT = {
  protect: '来源保护登记',
  verify: '登记来源核验',
  infer_single: '单样本模型评估',
  mea: '多模型单样本评估',
  compliance: '平台合规评估',
  legacy: '历史旧记录',
  unspecified: '未声明场景',
};

function resultTrust(payload, expectedScenario) {
  const value = payload || {};
  const scenario = String(expectedScenario || 'unspecified');
  const rawMode = String(value.mode || 'unavailable');
  const rawProvenance = String(value.result_provenance || '');
  const modeMeta = MODE[rawMode] || {
    kind: 'unavailable',
    text: 'UNAVAILABLE · 未知模式 ' + rawMode,
    cls: 'risk',
  };
  const provenanceMeta = PROVENANCE[rawProvenance];
  const expectedProvenance = EXPECTED_PROVENANCE[scenario] || '';
  const declaredClaimValid = value.claim_valid === true;

  let gateReason = 'citeable';
  if (!expectedProvenance) gateReason = 'unsupported_result_context';
  else if (rawMode !== 'real_checkpoint') gateReason = 'mode_not_real_checkpoint';
  else if (!declaredClaimValid) gateReason = 'claim_valid_not_true';
  else if (rawProvenance !== expectedProvenance) gateReason = 'result_provenance_mismatch';

  const citeable = gateReason === 'citeable';
  const scenarioText = SCENARIO_TEXT[scenario] || ('未知场景 ' + scenario);
  const provenanceText = provenanceMeta
    ? provenanceMeta.text
    : (rawProvenance ? 'UNTRUSTED · 未登记结果来源 ' + rawProvenance : 'UNTRUSTED · 缺失结果来源');

  return {
    mode: rawMode,
    modeKind: modeMeta.kind,
    modeText: modeMeta.text,
    modeClass: modeMeta.cls,
    expectedScenario: scenario,
    scenarioText,
    expectedProvenance,
    resultProvenance: rawProvenance,
    provenanceText,
    declaredClaimValid,
    // claimValid 为兼容现有页面的“有效门禁”字段；不等于后端原始 claim_valid。
    claimValid: citeable,
    citeable,
    gateReason,
    gateReasonText: citeable
      ? '三元门禁通过：模式、声明与登记来源一致'
      : (!expectedProvenance
        ? scenarioText + '不属于可引用来源场景'
        : '模式、声明或登记来源未同时满足'),
    claimText: citeable
      ? 'CLAIM VALID · ' + scenarioText + '结果可引用'
      : (expectedProvenance
        ? 'CLAIM INVALID · 禁止作来源/合规/取证结论'
        : 'EVALUATION ONLY · 禁止作来源/合规/取证结论'),
    claimClass: citeable ? 'ok' : 'risk',
  };
}

module.exports = { EXPECTED_PROVENANCE, PROVENANCE, resultTrust };
