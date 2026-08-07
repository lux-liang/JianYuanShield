'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { resultTrust } = require(path.join(ROOT, 'utils', 'trust'));
const history = require(path.join(ROOT, 'utils', 'history'));
const { fixed, pct, scoreClass } = require(path.join(ROOT, 'utils', 'format'));

function trust(payload, scenario) {
  return resultTrust(payload, scenario).citeable;
}

const protect = {
  mode: 'real_checkpoint',
  claim_valid: true,
  result_provenance: 'registered_protection_record',
};
const verify = {
  mode: 'real_checkpoint',
  claim_valid: true,
  result_provenance: 'registered_blind_verification',
};

assert.strictEqual(trust(protect, 'protect'), true, 'valid protection record must pass');
assert.strictEqual(trust(verify, 'verify'), true, 'valid registered verification must pass');
assert.strictEqual(pct(null), '—', 'missing metric must not render as 0%');
assert.strictEqual(fixed(undefined), '—', 'missing metric must not render as zero');
assert.strictEqual(scoreClass(null), 'muted', 'missing metric must not render as risk score');

[
  [{ ...protect, mode: 'demo_simulation' }, 'protect', 'demo mode'],
  [{ ...protect, mode: 'capability_unavailable' }, 'protect', 'unavailable mode'],
  [{ ...protect, claim_valid: false }, 'protect', 'false claim'],
  [{ ...protect, claim_valid: 'true' }, 'protect', 'string claim'],
  [{ ...protect, result_provenance: '' }, 'protect', 'missing provenance'],
  [verify, 'protect', 'verify provenance on protect page'],
  [protect, 'verify', 'protect provenance on verify page'],
  [protect, 'infer_single', 'infer-single context'],
  [verify, 'mea', 'MEA context'],
  [protect, undefined, 'missing context'],
].forEach(([payload, scenario, label]) => {
  assert.strictEqual(trust(payload, scenario), false, label + ' must fail closed');
});

const legacy = history.normalize({
  model: 'SepMark',
  verdictText: '模型阈值通过',
  claimValid: true,
});
assert.strictEqual(legacy.citeable, false, 'legacy history must fail closed');
assert.strictEqual(legacy.verdictText, '历史旧记录 · 不可引用');

const validProtectionHistory = history.normalize({
  scenario: 'protect',
  mode: protect.mode,
  declaredClaimValid: protect.claim_valid,
  resultProvenance: protect.result_provenance,
});
assert.strictEqual(validProtectionHistory.citeable, true, 'valid protection history must pass');

const forgedEvaluation = history.normalize({
  scenario: 'infer_single',
  mode: 'real_checkpoint',
  declaredClaimValid: true,
  resultProvenance: 'registered_protection_record',
});
assert.strictEqual(forgedEvaluation.citeable, false, 'evaluation history must never become citeable');

const pageFiles = [
  path.join(ROOT, 'pages', 'home', 'index.js'),
  path.join(ROOT, 'pages', 'mea', 'index.js'),
  path.join(ROOT, 'utils', 'history.js'),
];
pageFiles.forEach((file) => {
  const source = fs.readFileSync(file, 'utf8');
  const calls = source.match(/resultTrust\s*\([^\n;]+\)/g) || [];
  calls.forEach((call) => {
    assert.ok(call.includes(','), `${path.relative(ROOT, file)} has resultTrust call without explicit context: ${call}`);
  });
});

function assertViewStructure(viewRelative, scriptRelative) {
  const viewPath = path.join(ROOT, viewRelative);
  const scriptPath = path.join(ROOT, scriptRelative);
  const view = fs.readFileSync(viewPath, 'utf8').replace(/<!--[^]*?-->/g, '');
  const script = fs.readFileSync(scriptPath, 'utf8');
  const stack = [];
  const tagPattern = /<\/?([A-Za-z][\w-]*)\b[^>]*>/g;
  let match;
  while ((match = tagPattern.exec(view))) {
    const whole = match[0];
    const tag = match[1];
    if (whole.startsWith('</')) {
      assert.strictEqual(stack.pop(), tag, `${viewRelative} has unbalanced </${tag}>`);
    } else if (!whole.endsWith('/>')) stack.push(tag);
  }
  assert.deepStrictEqual(stack, [], `${viewRelative} has unclosed tags`);

  const handlers = [...view.matchAll(/\b(?:bind|catch)[\w:-]*="([A-Za-z_$][\w$]*)"/g)]
    .map((value) => value[1]);
  [...new Set(handlers)].forEach((handler) => {
    assert.ok(new RegExp(`\\b${handler}\\s*\\(`).test(script), `${viewRelative} references missing handler ${handler}`);
  });
}

assertViewStructure(path.join('pages', 'home', 'index.wxml'), path.join('pages', 'home', 'index.js'));
assertViewStructure(path.join('pages', 'mea', 'index.wxml'), path.join('pages', 'mea', 'index.js'));

const home = fs.readFileSync(path.join(ROOT, 'pages', 'home', 'index.js'), 'utf8');
const homeView = fs.readFileSync(path.join(ROOT, 'pages', 'home', 'index.wxml'), 'utf8');
const mea = fs.readFileSync(path.join(ROOT, 'pages', 'mea', 'index.js'), 'utf8');
assert.ok(home.includes("'/api/provenance/protect'"), 'protect endpoint must be wired');
assert.ok(home.includes("'/api/provenance/verify'"), 'verify endpoint must be wired');
assert.ok(home.includes("resultTrust(result, 'infer_single')"), 'infer-single must use non-citeable context');
assert.ok(mea.includes("resultTrust(r, 'mea')"), 'MEA must use non-citeable context');
assert.ok(mea.includes("request('/api/collaboration/recommend'"), 'MEA collaboration policy endpoint must be wired');
assert.ok(mea.includes("result.status !== 'recommendation_ready'"), 'MEA collaboration result must fail closed');
assert.ok(mea.includes("evidence.summary_sha256"), 'MEA collaboration view must expose its evidence binding');
assert.ok(mea.includes('assertPolicyResponse(payload, threats, profile)'), 'MEA collaboration response contract must be validated against its request');
assert.ok(mea.includes('evidence.signature_verified !== true'), 'MEA collaboration must require a verified release signature');
assert.ok(mea.includes('evidence.signer_pinned !== true'), 'MEA collaboration must require signer pinning');
assert.ok(mea.includes('evidence.policy_sha256'), 'MEA collaboration must bind the signed policy bytes');
assert.ok(mea.includes('simultaneous_lcb'), 'MEA collaboration must display confidence-adjusted metrics');

[
  ['一键取证', homeView],
  ['真实检查点输出 · 结论可引用', home],
  ['模型阈值通过', mea],
].forEach(([forbidden, source]) => {
  assert.ok(!source.includes(forbidden), `forbidden claim text reintroduced: ${forbidden}`);
});

process.stdout.write('miniprogram trust gate: PASS\n');
