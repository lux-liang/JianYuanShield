"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  MODEL_ORDER,
  SIMSWAP_RUN_ID,
  validateCollaborationResponse,
  validateModelStatus,
  validateSimSwapEvidence,
} = require("../system/frontend/trust-contracts.js");

const HASH = "a".repeat(64);
const FILE_NAMES = [
  "assets_manifest.json",
  "identity_embeddings.csv",
  "message_registry.json",
  "pair_manifest.json",
  "progress.json",
  "results.csv",
  "run_config.json",
  "summary.json",
];

function metric(successes, total, low, high) {
  return { successes, total, estimate: Number((successes / total).toFixed(8)), wilson_95_low: low, wilson_95_high: high };
}

function modelResult() {
  return {
    status: "complete",
    holdout: {
      pair_count: 192,
      tar: metric(191, 192, 0.9710925, 0.99908001),
      far: metric(0, 576, 0, 0.00662502),
      far_by_negative_control: {
        unwatermarked: metric(0, 192, 0, 0.01961515),
        wrong_message: metric(0, 192, 0, 0.01961515),
        cross_record: metric(0, 192, 0, 0.01961515),
      },
    },
    identity_migration: {
      clean_swap: metric(161, 192, 0.77994169, 0.88386055),
      watermarked_swap: metric(157, 192, 0.75704577, 0.86590711),
    },
  };
}

function simswapFixture() {
  const modelResults = Object.fromEntries(MODEL_ORDER.map((model) => [model, modelResult()]));
  const conditioned = {
    LIDMark: [[128, 161, 0.72, 0.86], [123, 150, 0.75, 0.88]],
    "KAD-Net": [[160, 161, 0.96566044, 0.99890273], [153, 154, 0.96413879, 0.99885282]],
    SepMark: [[151, 161, 0.88945175, 0.96591559], [150, 159, 0.89593484, 0.96993802]],
    WaveGuard: [[82, 161, 0.43278442, 0.58541488], [78, 156, 0.42248721, 0.57751279]],
  };
  const scopedResults = Object.fromEntries(MODEL_ORDER.map((model) => {
    const counts = conditioned[model];
    return [model, {
      holdout_tar: modelResults[model].holdout.tar,
      holdout_far: modelResults[model].holdout.far,
      holdout_far_by_negative_control: modelResults[model].holdout.far_by_negative_control,
      identity_migration: modelResults[model].identity_migration,
      registered_positive_conditioned_on_identity_migration: {
        clean_swap_migrated: metric(...counts[0]),
        clean_and_watermarked_swap_migrated: metric(...counts[1]),
      },
    }];
  }));
  return {
    schema_version: "simswap-lfw-benchmark.v1",
    evidence_schema_version: "simswap-lfw-robustness-summary.v1",
    run_class: "real_n256_evidence",
    method: "official SimSwap",
    run_id: SIMSWAP_RUN_ID,
    scope: { dataset: "LFW", num_pairs: 256, calibration_pairs: 64, holdout_pairs: 192, identity_overlap_count: 0 },
    models: [...MODEL_ORDER],
    controls: ["registered_positive", "unwatermarked_negative", "wrong_message_negative", "cross_record_negative"],
    model_results: modelResults,
    engine: {
      engine: "SimSwap",
      mode: "official_release_checkpoint",
      source_commit: "b".repeat(40),
      source_tree: "c".repeat(40),
      source_tracked_files_sha256: HASH,
      checkpoint_archive_sha256: HASH,
      generator_checkpoint_sha256: HASH,
      arcface_checkpoint_sha256: HASH,
      input_size: 224,
      identity_embedding_dim: 512,
    },
    coverage: {
      num_pairs: 256,
      calibration_pairs: 64,
      holdout_pairs: 192,
      result_rows: 1024,
      expected_result_rows: 1024,
      identity_embedding_rows: 1792,
      expected_identity_embedding_rows: 1792,
      error_rows: 0,
      identity_overlap_count: 0,
      asset_count: 176,
      expected_asset_count: 176,
    },
    release_gate: {
      schema_verified: true,
      run_id_verified: true,
      coverage_verified: true,
      model_contract_verified: true,
      official_engine_verified: true,
      implementation_hashes_verified: true,
      signature_verified: true,
      signer_pinned: true,
    },
    status: "verified",
    claim_valid: true,
    claim_status: "evidence_verified",
    evidence_validation: {
      schema_version: "simswap-lfw-evidence-status.v1",
      valid: true,
      status: "verified",
      run_id: SIMSWAP_RUN_ID,
      num_pairs: 256,
      calibration_pairs: 64,
      holdout_pairs: 192,
      result_rows: 1024,
      identity_embedding_rows: 1792,
      identity_overlap_count: 0,
      asset_count: 176,
      identity_migration_evidence_scope: {
        schema_version: "simswap-identity-migration-evidence-scope.v1",
        scope: "pipeline_internal_identity_migration_evidence",
        method: "source_cosine_greater_than_target_cosine",
        arcface_checkpoint_path: "weights/SimSwap/downloads/arcface_checkpoint.tar",
        arcface_checkpoint_sha256: HASH,
        same_arcface_checkpoint_used_for_generation_and_measurement: true,
        independent_identity_verifier: false,
      },
      model_results: scopedResults,
      evidence_files: Object.fromEntries(FILE_NAMES.map((name) => [name, { path: `reports/${SIMSWAP_RUN_ID}/${name}`, sha256: HASH }])),
      signature: {
        schema_version: "evidence-signature-status.v1",
        status: "verified",
        verified: true,
        signature_valid: true,
        signer_pinned: true,
        profile: "release-core",
        mismatches: [],
        manifest_sha256: HASH,
        public_key_fingerprint_sha256: HASH,
      },
      errors: [],
    },
  };
}

const valid = validateSimSwapEvidence(simswapFixture());
const kad = valid.rows.find((row) => row.model === "KAD-Net");
assert.equal(kad.tar.successes, 191);
assert.equal(kad.tar.low, 0.9710925);
assert.equal(kad.far.estimate, 0);
assert.equal(kad.controls[0].successes, 0);
assert.equal(kad.controls[0].total, 192);
assert.equal(kad.controls[0].high, 0.01961515);

for (const mutate of [
  (value) => { value.claim_valid = false; },
  (value) => { value.schema_version = "simswap-lfw-benchmark.v0"; },
  (value) => { value.run_id = "forged"; },
  (value) => { value.coverage.result_rows = 1023; },
  (value) => { value.release_gate.implementation_hashes_verified = false; },
  (value) => { value.evidence_validation.signature.signer_pinned = false; },
  (value) => { value.evidence_validation.signature.manifest_sha256 = "not-a-hash"; },
  (value) => { value.evidence_validation.identity_migration_evidence_scope.independent_identity_verifier = true; },
  (value) => { value.evidence_validation.model_results["KAD-Net"].registered_positive_conditioned_on_identity_migration.clean_swap_migrated.successes = 159; },
  (value) => { value.model_results["KAD-Net"].holdout.far.successes = 1; },
]) {
  const forged = simswapFixture();
  mutate(forged);
  assert.throws(() => validateSimSwapEvidence(forged));
}

const collaborationProfile = {
  risk_aversion: 0.6,
  fidelity_weight: 0.2,
  minimum_worst_case_protocol_normalized_margin: 0.45,
};
const collaborationThreats = MODEL_ORDER.map((model) => ({ model, exposure: 1 }));

function collaborationFixture() {
  const ranking = MODEL_ORDER.map((model, index) => ({
    model,
    feasible: index === 0,
    pareto_optimal: index === 0,
    score: 0.8 - index * 0.1,
    expected_source_protocol_normalized_margin_cluster_lcb: 0.8 - index * 0.05,
    worst_case_source_protocol_normalized_margin_cluster_lcb: 0.7 - index * 0.05,
    worst_case_source_protocol_success_rate_cluster_lcb: index === 0 ? 0.7 : 0.4,
    worst_case_post_attack_ssim_cluster_lcb: 0.8,
    fidelity_score: 0.7,
    constraint_violations: index === 0 ? [] : ["worst_case_protocol_success_rate_cluster_lcb_below_floor"],
  }));
  const recommendation = {
    ...ranking[0],
    low_risk_interaction_models: ["KAD-Net"],
    rationale_codes: [
      "highest_feasible_confidence_adjusted_score",
      "content_addressed_mea_evidence",
      "feasible_domain_pareto_frontier",
      "identity_cluster_bootstrap_simultaneous_bounds",
      "protocol_normalized_cross_model_estimand",
    ],
  };
  return {
    schema_version: "collaboration-recommendation.v2",
    status: "recommendation_ready",
    recommendation,
    ranking,
    interaction_plan: MODEL_ORDER.map((attacker) => ({
      source_model: "LIDMark",
      attacker_model: attacker,
      policy_hint: "planned_block_second_embedding",
      source_protocol_normalized_margin_cluster_lcb: 0.7,
      attacker_protocol_normalized_margin_cluster_lcb: 0.6,
      source_protocol_success_rate_cluster_lcb: 0.7,
      attacker_protocol_success_rate_cluster_lcb: 0.6,
    })),
    request: {
      threat_probabilities: Object.fromEntries(MODEL_ORDER.map((model) => [model, 0.25])),
      candidate_models: [...MODEL_ORDER],
      ...collaborationProfile,
    },
    scoring: {
      confidence_level: 0.95,
      uncertainty_method: "deterministic_identity_cluster_bootstrap_percentile",
      cluster_key: "lfw_filename_identity_prefix_v1",
      estimand: "equal_identity_weighted_mean_of_within_identity_image_means",
      normalized_margin_transform: "piecewise_linear_protocol_threshold_centered_at_0_5",
      raw_bit_accuracy_use: "diagnostic_only_not_cross_model_ranked",
      bootstrap_rng: "numpy_pcg64_multinomial",
      bootstrap_seed: 20260603,
      bootstrap_resamples: 20000,
      bootstrap_quantile_method: "lower",
      multiplicity_adjustment: "bonferroni_one_sided_fixed_full_selection_family",
      family_scope: "all_4_candidates_x_all_4_attackers_x_6_metrics_including_post_selection",
      family_metrics: [
        "source_protocol_normalized_margin", "source_protocol_success",
        "attacker_protocol_normalized_margin", "attacker_protocol_success",
        "second_vs_original_psnr", "second_vs_original_ssim",
      ],
      family_size: 96,
      per_comparison_alpha: 0.00052083,
      image_count: 256,
      identity_count: 217,
      repeated_identity_count: 24,
      images_in_repeated_identities: 63,
      max_cluster_size: 10,
      model_semantics: {
        LIDMark: { message_length: 16, primary_decoder: "FHD_id_head", success_threshold: 0.9 },
        "KAD-Net": { message_length: 30, primary_decoder: "ST_Decoder_C", success_threshold: 0.9 },
        SepMark: { message_length: 128, primary_decoder: "decoder_C", success_threshold: 0.9 },
        WaveGuard: { message_length: 30, primary_decoder: "tracer", success_threshold: 0.9 },
      },
      pareto_dimensions: [
        "expected_source_protocol_normalized_margin_cluster_lcb",
        "worst_case_source_protocol_success_rate_cluster_lcb",
        "fidelity_score",
      ],
      tie_break_model_order: [...MODEL_ORDER],
      hard_constraints: {
        minimum_worst_case_protocol_normalized_margin_cluster_lcb: 0.45,
        minimum_worst_case_source_protocol_success_rate_cluster_lcb: 0.5,
        minimum_worst_case_post_attack_psnr_cluster_lcb_db: 20,
        minimum_worst_case_post_attack_ssim_cluster_lcb: 0.6,
      },
      selection_stability: {
        method: "cluster_resample_point_policy_selection_frequency",
        resamples: 20000,
        selection_frequency: { LIDMark: 1, "KAD-Net": 0, SepMark: 0, WaveGuard: 0, none: 0 },
        selected_model_frequency: 1,
      },
    },
    ablation: {
      legacy_iid_raw_accuracy: {
        method: "legacy_raw_bit_accuracy_iid_normal_wilson_diagnostic_only",
        selected_model: "LIDMark",
        feasible_models: ["LIDMark"],
      },
      identity_cluster_normalized_policy_selected_model: "LIDMark",
      selection_changed: false,
    },
    evidence: {
      images_per_cell: 256,
      image_count: 256,
      identity_count: 217,
      repeated_identity_count: 24,
      images_in_repeated_identities: 63,
      max_cluster_size: 10,
      cells: 16,
      rows: 4096,
      summary_sha256: HASH,
      policy_sha256: HASH,
      protocol_sha256: HASH,
      content_verified: true,
      signature_verified: true,
      signer_pinned: true,
      release_signature: {
        verified: true,
        signer_pinned: true,
        profile: "release-core",
        policy_sha256: HASH,
        manifest_sha256: HASH,
        public_key_fingerprint_sha256: HASH,
      },
    },
  };
}

assert.equal(
  validateCollaborationResponse(
    collaborationFixture(), collaborationThreats, collaborationProfile,
  ).recommendation.model,
  "LIDMark",
);
for (const mutate of [
  (value) => { value.schema_version = "collaboration-recommendation.v1"; },
  (value) => { value.evidence.identity_count = 256; },
  (value) => { value.scoring.family_size = 24; },
  (value) => { value.scoring.bootstrap_seed = 1; },
  (value) => { value.scoring.model_semantics.SepMark.message_length = 30; },
  (value) => { value.scoring.selection_stability.selection_frequency.LIDMark = 0.9; },
  (value) => { value.interaction_plan[0].policy_hint = "allow_only_with_dual_provenance_record"; },
]) {
  const forged = collaborationFixture();
  mutate(forged);
  assert.throws(() => validateCollaborationResponse(forged, collaborationThreats, collaborationProfile));
}

function blockedStatus() {
  return {
    available: true,
    loaded: false,
    checkpoint_sha256: HASH,
    registered: false,
    calibrated: false,
    trusted: false,
    provenance_ready: false,
    verification_threshold: null,
    reason_codes: ["checkpoint_unregistered", "calibration_unverified", "weight_manifest_untrusted"],
  };
}

const modelPayload = {
  schema_version: "model-provenance-status.v1",
  preferred_model: "KAD-Net",
  ...Object.fromEntries(MODEL_ORDER.map((model) => [model, blockedStatus()])),
};
modelPayload["KAD-Net"] = {
  available: true,
  loaded: false,
  checkpoint_sha256: HASH,
  registered: true,
  calibrated: true,
  trusted: true,
  provenance_ready: true,
  verification_threshold: 0.7666666666666668,
  reason_codes: [],
};
const modelContract = validateModelStatus(modelPayload);
assert.equal(modelContract.preferredModel, "KAD-Net");
assert.deepEqual(modelContract.options.filter((item) => item.provenance_ready).map((item) => item.model), ["KAD-Net"]);
const forgedModelStatus = structuredClone(modelPayload);
forgedModelStatus.LIDMark.provenance_ready = true;
assert.throws(() => validateModelStatus(forgedModelStatus));

const root = path.resolve(__dirname, "..");
const web = fs.readFileSync(path.join(root, "system/frontend/index.html"), "utf8");
const webApp = fs.readFileSync(path.join(root, "system/frontend/app.js"), "utf8");
const miniHome = fs.readFileSync(path.join(root, "miniprogram/pages/home/index.js"), "utf8");
const miniMea = fs.readFileSync(path.join(root, "miniprogram/pages/mea/index.wxml"), "utf8");
assert.ok(web.includes("第三方底层模型与项目集成、协议创新、证据验链等系统增量"));
assert.ok(web.includes("只输出部署建议，不自动执行双水印"));
assert.ok(webApp.includes("PLANNED POLICY HINT"));
assert.ok(miniHome.includes("第三方底层模型"));
assert.ok(miniMea.includes("只生成建议，不自动执行双水印"));
for (const forbidden of ["团队原创方法", "t: '原创'", "冲突解释与执行动作", "双水印共存"]) {
  assert.equal([web, webApp, miniHome, miniMea].some((content) => content.includes(forbidden)), false, `forbidden wording: ${forbidden}`);
}

console.log("frontend trust contracts: ok");
