(function initTrustContracts(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.JYSTrustContracts = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function buildTrustContracts() {
  "use strict";

  const MODEL_ORDER = Object.freeze(["LIDMark", "KAD-Net", "SepMark", "WaveGuard"]);
  const SIMSWAP_RUN_ID = "simswap-lfw-robustness-n256-s20260603";
  const NEGATIVE_CONTROLS = Object.freeze(["unwatermarked", "wrong_message", "cross_record"]);
  const SUMMARY_CONTROLS = Object.freeze([
    "registered_positive",
    "unwatermarked_negative",
    "wrong_message_negative",
    "cross_record_negative",
  ]);
  const EVIDENCE_FILES = Object.freeze([
    "assets_manifest.json",
    "identity_embeddings.csv",
    "message_registry.json",
    "pair_manifest.json",
    "progress.json",
    "results.csv",
    "run_config.json",
    "summary.json",
  ]);
  const MODEL_REASON_CODES = Object.freeze([
    "checkpoint_unavailable_or_hash_mismatch",
    "checkpoint_unregistered",
    "calibration_unverified",
    "weight_manifest_untrusted",
  ]);
  const CONDITIONED_MIGRATION_COUNTS = Object.freeze({
    LIDMark: Object.freeze([[128, 161], [123, 150]]),
    "KAD-Net": Object.freeze([[160, 161], [153, 154]]),
    SepMark: Object.freeze([[151, 161], [150, 159]]),
    WaveGuard: Object.freeze([[82, 161], [78, 156]]),
  });
  const COLLABORATION_FAMILY_METRICS = Object.freeze([
    "source_protocol_normalized_margin",
    "source_protocol_success",
    "attacker_protocol_normalized_margin",
    "attacker_protocol_success",
    "second_vs_original_psnr",
    "second_vs_original_ssim",
  ]);
  const COLLABORATION_VIOLATIONS = Object.freeze([
    "worst_case_protocol_normalized_margin_cluster_lcb_below_floor",
    "worst_case_protocol_success_rate_cluster_lcb_below_floor",
    "worst_case_post_attack_psnr_cluster_lcb_below_floor",
    "worst_case_post_attack_ssim_cluster_lcb_below_floor",
  ]);
  const COLLABORATION_HINTS = Object.freeze([
    "planned_dual_provenance_before_allow",
    "planned_reject_unverifiable_second_embedding",
    "planned_block_or_isolate_second_embedding",
    "planned_block_second_embedding",
  ]);

  function fail(message) {
    throw new Error(message);
  }

  function object(value, label) {
    if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${label} 结构无效`);
    return value;
  }

  function exactInteger(value, expected, label) {
    if (!Number.isInteger(value) || value !== expected) fail(`${label} 必须为 ${expected}`);
  }

  function finiteUnit(value, label) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
      fail(`${label} 必须为 [0,1] 有限数`);
    }
    return value;
  }

  function hash(value, label) {
    if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) fail(`${label} 必须为 SHA-256`);
    return value;
  }

  function exactArray(value, expected, label) {
    if (!Array.isArray(value) || value.length !== expected.length
      || expected.some((item, index) => value[index] !== item)) {
      fail(`${label} 成员或顺序不符合固定契约`);
    }
  }

  function exactKeys(value, expected, label) {
    const keys = Object.keys(object(value, label)).sort();
    const wanted = [...expected].sort();
    if (JSON.stringify(keys) !== JSON.stringify(wanted)) fail(`${label} 成员不符合固定契约`);
  }

  function approximately(actual, expected, label) {
    if (Math.abs(actual - expected) > 5e-8) fail(`${label} 与计数不可复算`);
  }

  function wilsonMetric(value, total, label) {
    const metric = object(value, label);
    if (!Number.isInteger(metric.successes) || metric.successes < 0 || metric.successes > total) {
      fail(`${label}.successes 无效`);
    }
    exactInteger(metric.total, total, `${label}.total`);
    const estimate = finiteUnit(metric.estimate, `${label}.estimate`);
    const low = finiteUnit(metric.wilson_95_low, `${label}.wilson_95_low`);
    const high = finiteUnit(metric.wilson_95_high, `${label}.wilson_95_high`);
    approximately(estimate, metric.successes / total, `${label}.estimate`);
    if (low > estimate || estimate > high) fail(`${label} Wilson 区间顺序无效`);
    return { successes: metric.successes, total, estimate, low, high };
  }

  function validateSimSwapEvidence(payload) {
    const response = object(payload, "SimSwap 响应");
    if (response.schema_version !== "simswap-lfw-benchmark.v1") fail("SimSwap API schema 不匹配");
    if (response.evidence_schema_version !== "simswap-lfw-robustness-summary.v1") fail("SimSwap summary schema 不匹配");
    if (response.run_class !== "real_n256_evidence") fail("SimSwap run_class 必须为真实 n256 证据");
    if (response.run_id !== SIMSWAP_RUN_ID) fail("SimSwap run_id 不匹配固定证据");
    if (response.method !== "official SimSwap") fail("换脸引擎声明不匹配");
    if (response.status !== "verified" || response.claim_valid !== true
      || response.claim_status !== "evidence_verified") {
      fail("claim_valid 未放行");
    }

    const scope = object(response.scope, "scope");
    if (scope.dataset !== "LFW") fail("数据集必须为 LFW");
    exactInteger(scope.num_pairs, 256, "scope.num_pairs");
    exactInteger(scope.calibration_pairs, 64, "scope.calibration_pairs");
    exactInteger(scope.holdout_pairs, 192, "scope.holdout_pairs");
    exactInteger(scope.identity_overlap_count, 0, "scope.identity_overlap_count");

    const coverage = object(response.coverage, "coverage");
    const coverageExpected = {
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
    };
    Object.entries(coverageExpected).forEach(([key, expected]) => exactInteger(coverage[key], expected, `coverage.${key}`));

    const gate = object(response.release_gate, "release_gate");
    [
      "schema_verified",
      "run_id_verified",
      "coverage_verified",
      "model_contract_verified",
      "official_engine_verified",
      "implementation_hashes_verified",
      "signature_verified",
      "signer_pinned",
    ].forEach((key) => {
      if (gate[key] !== true) fail(`release_gate.${key} 未通过`);
    });

    const validation = object(response.evidence_validation, "evidence_validation");
    if (validation.schema_version !== "simswap-lfw-evidence-status.v1"
      || validation.valid !== true || validation.status !== "verified"
      || validation.run_id !== SIMSWAP_RUN_ID) {
      fail("后端证据校验状态未通过");
    }
    exactInteger(validation.num_pairs, 256, "validation.num_pairs");
    exactInteger(validation.calibration_pairs, 64, "validation.calibration_pairs");
    exactInteger(validation.holdout_pairs, 192, "validation.holdout_pairs");
    exactInteger(validation.result_rows, 1024, "validation.result_rows");
    exactInteger(validation.identity_embedding_rows, 1792, "validation.identity_embedding_rows");
    exactInteger(validation.identity_overlap_count, 0, "validation.identity_overlap_count");
    exactInteger(validation.asset_count, 176, "validation.asset_count");
    if (!Array.isArray(validation.errors) || validation.errors.length !== 0) fail("证据校验仍含错误");

    const identityScope = object(
      validation.identity_migration_evidence_scope,
      "identity_migration_evidence_scope",
    );
    if (identityScope.schema_version !== "simswap-identity-migration-evidence-scope.v1"
      || identityScope.scope !== "pipeline_internal_identity_migration_evidence"
      || identityScope.method !== "source_cosine_greater_than_target_cosine"
      || identityScope.arcface_checkpoint_path !== "weights/SimSwap/downloads/arcface_checkpoint.tar"
      || identityScope.same_arcface_checkpoint_used_for_generation_and_measurement !== true
      || identityScope.independent_identity_verifier !== false) {
      fail("流程内身份迁移证据 scope 不匹配");
    }
    hash(identityScope.arcface_checkpoint_sha256, "identity scope ArcFace checkpoint");

    const signature = object(validation.signature, "signature");
    if (signature.schema_version !== "evidence-signature-status.v1"
      || signature.status !== "verified" || signature.verified !== true
      || signature.signature_valid !== true || signature.signer_pinned !== true
      || !["release-core", "release"].includes(signature.profile)
      || !Array.isArray(signature.mismatches) || signature.mismatches.length !== 0) {
      fail("Ed25519 release 签名或 signer pinning 未通过");
    }
    hash(signature.manifest_sha256, "signature.manifest_sha256");
    hash(signature.public_key_fingerprint_sha256, "signature.public_key_fingerprint_sha256");

    exactKeys(validation.evidence_files, EVIDENCE_FILES, "evidence_files");
    EVIDENCE_FILES.forEach((name) => {
      const file = object(validation.evidence_files[name], `evidence_files.${name}`);
      if (typeof file.path !== "string" || !file.path) fail(`evidence_files.${name}.path 无效`);
      hash(file.sha256, `evidence_files.${name}.sha256`);
    });

    exactArray(response.models, MODEL_ORDER, "models");
    exactArray(response.controls, SUMMARY_CONTROLS, "controls");
    exactKeys(response.model_results, MODEL_ORDER, "model_results");
    exactKeys(validation.model_results, MODEL_ORDER, "validation.model_results");

    const engine = object(response.engine, "engine");
    if (engine.engine !== "SimSwap" || engine.mode !== "official_release_checkpoint"
      || !/^[0-9a-f]{40}$/.test(engine.source_commit || "")
      || !/^[0-9a-f]{40}$/.test(engine.source_tree || "")) {
      fail("官方 SimSwap engine/commit/tree 契约未通过");
    }
    [
      "source_tracked_files_sha256",
      "checkpoint_archive_sha256",
      "generator_checkpoint_sha256",
      "arcface_checkpoint_sha256",
    ].forEach((key) => hash(engine[key], `engine.${key}`));
    exactInteger(engine.input_size, 224, "engine.input_size");
    exactInteger(engine.identity_embedding_dim, 512, "engine.identity_embedding_dim");

    const rows = MODEL_ORDER.map((model) => {
      const result = object(response.model_results[model], `model_results.${model}`);
      if (result.status !== "complete") fail(`${model} 结果不完整`);
      const holdout = object(result.holdout, `${model}.holdout`);
      exactInteger(holdout.pair_count, 192, `${model}.holdout.pair_count`);
      const tar = wilsonMetric(holdout.tar, 192, `${model}.tar`);
      const far = wilsonMetric(holdout.far, 576, `${model}.far`);
      exactKeys(holdout.far_by_negative_control, NEGATIVE_CONTROLS, `${model}.far_by_negative_control`);
      const controls = NEGATIVE_CONTROLS.map((name) => ({
        name,
        ...wilsonMetric(holdout.far_by_negative_control[name], 192, `${model}.${name}`),
      }));
      if (controls.reduce((sum, item) => sum + item.successes, 0) !== far.successes) {
        fail(`${model} aggregate FAR 与逐控制计数不一致`);
      }
      const identity = object(result.identity_migration, `${model}.identity_migration`);
      const cleanIdentity = wilsonMetric(identity.clean_swap, 192, `${model}.identity.clean`);
      const watermarkedIdentity = wilsonMetric(identity.watermarked_swap, 192, `${model}.identity.watermarked`);

      const scoped = object(validation.model_results[model], `validation.model_results.${model}`);
      if (JSON.stringify(scoped.holdout_tar) !== JSON.stringify(result.holdout.tar)
        || JSON.stringify(scoped.holdout_far) !== JSON.stringify(result.holdout.far)
        || JSON.stringify(scoped.holdout_far_by_negative_control)
          !== JSON.stringify(result.holdout.far_by_negative_control)
        || JSON.stringify(scoped.identity_migration) !== JSON.stringify(result.identity_migration)) {
        fail(`${model} API 指标与验链结果不一致`);
      }
      const conditioned = object(
        scoped.registered_positive_conditioned_on_identity_migration,
        `${model}.conditioned_identity_migration`,
      );
      exactKeys(conditioned, [
        "clean_swap_migrated",
        "clean_and_watermarked_swap_migrated",
      ], `${model}.conditioned_identity_migration`);
      const expectedCounts = CONDITIONED_MIGRATION_COUNTS[model];
      const cleanConditioned = wilsonMetric(
        conditioned.clean_swap_migrated,
        expectedCounts[0][1],
        `${model}.conditioned.clean`,
      );
      const watermarkedConditioned = wilsonMetric(
        conditioned.clean_and_watermarked_swap_migrated,
        expectedCounts[1][1],
        `${model}.conditioned.watermarked`,
      );
      if (cleanConditioned.successes !== expectedCounts[0][0]
        || watermarkedConditioned.successes !== expectedCounts[1][0]) {
        fail(`${model} 身份迁移条件下登记正例计数不匹配`);
      }
      return {
        model,
        tar,
        far,
        controls,
        worstControlFarUcb: Math.max(...controls.map((item) => item.high)),
        cleanIdentity,
        watermarkedIdentity,
        conservativeIdentityLcb: Math.min(cleanIdentity.low, watermarkedIdentity.low),
        cleanConditioned,
        watermarkedConditioned,
        conservativeConditionedLcb: Math.min(
          cleanConditioned.low,
          watermarkedConditioned.low,
        ),
      };
    });

    return { response, coverage, validation, signature, engine, identityScope, rows };
  }

  function validateModelStatus(payload) {
    const response = object(payload, "models/status 响应");
    if (response.schema_version !== "model-provenance-status.v1") fail("模型状态 schema 不匹配");
    const options = MODEL_ORDER.map((model) => {
      const status = object(response[model], `models/status.${model}`);
      ["available", "loaded", "registered", "calibrated", "trusted", "provenance_ready"].forEach((key) => {
        if (typeof status[key] !== "boolean") fail(`${model}.${key} 必须是布尔值`);
      });
      hash(status.checkpoint_sha256, `${model}.checkpoint_sha256`);
      if (status.calibrated) finiteUnit(status.verification_threshold, `${model}.verification_threshold`);
      else if (status.verification_threshold !== null) fail(`${model} 未校准时阈值必须为 null`);
      if (!Array.isArray(status.reason_codes)
        || new Set(status.reason_codes).size !== status.reason_codes.length
        || status.reason_codes.some((code) => !MODEL_REASON_CODES.includes(code))) {
        fail(`${model}.reason_codes 无效`);
      }
      const ready = status.available && status.registered && status.calibrated && status.trusted;
      if (status.provenance_ready !== ready) fail(`${model}.provenance_ready 与子门禁不一致`);
      const requiredReasons = [
        !status.available && "checkpoint_unavailable_or_hash_mismatch",
        !status.registered && "checkpoint_unregistered",
        !status.calibrated && "calibration_unverified",
        !status.trusted && "weight_manifest_untrusted",
      ].filter(Boolean);
      if (requiredReasons.some((code) => !status.reason_codes.includes(code))
        || (ready && status.reason_codes.length !== 0)) {
        fail(`${model}.reason_codes 未完整解释门禁`);
      }
      return { model, ...status };
    });
    const readyModels = options.filter((item) => item.provenance_ready);
    const expectedPreferred = readyModels.length ? readyModels[0].model : null;
    if (response.preferred_model !== expectedPreferred) fail("preferred_model 必须指向首个可信来源模型");
    return { response, options, preferredModel: expectedPreferred };
  }

  function validateCollaborationResponse(payload, requestedThreats, requestedProfile) {
    const response = object(payload, "协同响应");
    if (response.schema_version !== "collaboration-recommendation.v2") fail("协同响应 schema 不匹配");
    if (!requestedProfile || !Array.isArray(requestedThreats) || !requestedThreats.length) {
      fail("协同请求回显校验上下文缺失");
    }
    const evidence = object(response.evidence, "evidence");
    const signature = object(evidence.release_signature, "release_signature");
    if (evidence.content_verified !== true || evidence.signature_verified !== true
      || evidence.signer_pinned !== true || signature.verified !== true
      || signature.signer_pinned !== true || !["release-core", "release"].includes(signature.profile)) {
      fail("release-core 签名证据未通过");
    }
    exactInteger(evidence.images_per_cell, 256, "evidence.images_per_cell");
    exactInteger(evidence.image_count, 256, "evidence.image_count");
    exactInteger(evidence.identity_count, 217, "evidence.identity_count");
    exactInteger(evidence.repeated_identity_count, 24, "evidence.repeated_identity_count");
    exactInteger(evidence.images_in_repeated_identities, 63, "evidence.images_in_repeated_identities");
    exactInteger(evidence.max_cluster_size, 10, "evidence.max_cluster_size");
    exactInteger(evidence.cells, 16, "evidence.cells");
    exactInteger(evidence.rows, 4096, "evidence.rows");
    ["summary_sha256", "policy_sha256", "protocol_sha256"].forEach((key) => hash(evidence[key], `evidence.${key}`));
    hash(signature.manifest_sha256, "signature.manifest_sha256");
    hash(signature.public_key_fingerprint_sha256, "signature.public_key_fingerprint_sha256");
    if (signature.policy_sha256 !== evidence.policy_sha256) fail("签名未绑定返回策略哈希");

    const requestEcho = object(response.request, "request");
    exactArray(requestEcho.candidate_models, MODEL_ORDER, "request.candidate_models");
    ["risk_aversion", "fidelity_weight", "minimum_worst_case_protocol_normalized_margin"]
      .forEach((key) => finiteUnit(requestEcho[key], `request.${key}`));
    if (requestEcho.risk_aversion !== requestedProfile.risk_aversion
      || requestEcho.fidelity_weight !== requestedProfile.fidelity_weight
      || requestEcho.minimum_worst_case_protocol_normalized_margin
        !== requestedProfile.minimum_worst_case_protocol_normalized_margin) {
      fail("协同请求回显与提交策略不一致");
    }
    const expectedThreatModels = requestedThreats.map((item) => item.model).sort();
    const probabilities = object(requestEcho.threat_probabilities, "request.threat_probabilities");
    exactKeys(probabilities, expectedThreatModels, "request.threat_probabilities");
    const totalExposure = requestedThreats.reduce((sum, item) => sum + item.exposure, 0);
    expectedThreatModels.forEach((model) => {
      const exposure = requestedThreats.find((item) => item.model === model).exposure;
      finiteUnit(probabilities[model], `request.threat_probabilities.${model}`);
      approximately(probabilities[model], exposure / totalExposure, `request.threat_probabilities.${model}`);
    });

    const scoring = object(response.scoring, "scoring");
    if (scoring.confidence_level !== 0.95
      || scoring.uncertainty_method !== "deterministic_identity_cluster_bootstrap_percentile"
      || scoring.cluster_key !== "lfw_filename_identity_prefix_v1"
      || scoring.estimand !== "equal_identity_weighted_mean_of_within_identity_image_means"
      || scoring.normalized_margin_transform !== "piecewise_linear_protocol_threshold_centered_at_0_5"
      || scoring.raw_bit_accuracy_use !== "diagnostic_only_not_cross_model_ranked"
      || scoring.bootstrap_rng !== "numpy_pcg64_multinomial"
      || scoring.bootstrap_seed !== 20260603 || scoring.bootstrap_resamples !== 20000
      || scoring.bootstrap_quantile_method !== "lower"
      || scoring.multiplicity_adjustment !== "bonferroni_one_sided_fixed_full_selection_family"
      || scoring.family_scope !== "all_4_candidates_x_all_4_attackers_x_6_metrics_including_post_selection"
      || scoring.family_size !== 96) {
      fail("身份聚类 bootstrap 方法或固定选择族不匹配");
    }
    exactArray(scoring.family_metrics, COLLABORATION_FAMILY_METRICS, "scoring.family_metrics");
    approximately(scoring.per_comparison_alpha, 0.05 / 96, "scoring.per_comparison_alpha");
    ["image_count", "identity_count", "repeated_identity_count", "images_in_repeated_identities", "max_cluster_size"]
      .forEach((key) => exactInteger(scoring[key], evidence[key], `scoring.${key}`));
    exactArray(scoring.pareto_dimensions, [
      "expected_source_protocol_normalized_margin_cluster_lcb",
      "worst_case_source_protocol_success_rate_cluster_lcb",
      "fidelity_score",
    ], "scoring.pareto_dimensions");
    exactArray(scoring.tie_break_model_order, MODEL_ORDER, "scoring.tie_break_model_order");
    const semantics = object(scoring.model_semantics, "scoring.model_semantics");
    exactKeys(semantics, MODEL_ORDER, "scoring.model_semantics");
    const expectedSemantics = {
      LIDMark: [16, "FHD_id_head"],
      "KAD-Net": [30, "ST_Decoder_C"],
      SepMark: [128, "decoder_C"],
      WaveGuard: [30, "tracer"],
    };
    MODEL_ORDER.forEach((model) => {
      const semantic = object(semantics[model], `semantics.${model}`);
      if (semantic.message_length !== expectedSemantics[model][0]
        || semantic.primary_decoder !== expectedSemantics[model][1]
        || semantic.success_threshold !== 0.9) fail(`${model} 协议语义不匹配`);
    });
    const constraints = object(scoring.hard_constraints, "scoring.hard_constraints");
    if (constraints.minimum_worst_case_protocol_normalized_margin_cluster_lcb
        !== requestEcho.minimum_worst_case_protocol_normalized_margin
      || constraints.minimum_worst_case_source_protocol_success_rate_cluster_lcb !== 0.5
      || constraints.minimum_worst_case_post_attack_psnr_cluster_lcb_db !== 20
      || constraints.minimum_worst_case_post_attack_ssim_cluster_lcb !== 0.6) {
      fail("硬约束未按签名策略执行");
    }
    const stability = object(scoring.selection_stability, "scoring.selection_stability");
    if (stability.method !== "cluster_resample_point_policy_selection_frequency"
      || stability.resamples !== 20000) fail("选择稳定性方法不匹配");
    const frequencies = object(stability.selection_frequency, "selection_frequency");
    exactKeys(frequencies, [...MODEL_ORDER, "none"], "selection_frequency");
    const frequencyTotal = Object.values(frequencies).reduce((sum, value) => sum + finiteUnit(value, "selection_frequency value"), 0);
    approximately(frequencyTotal, 1, "selection_frequency total");

    const ranking = response.ranking;
    if (!Array.isArray(ranking) || ranking.length !== 4) fail("排序未覆盖四个候选");
    exactKeys(Object.fromEntries(ranking.map((item) => [item.model, true])), MODEL_ORDER, "ranking models");
    ranking.forEach((item) => {
      object(item, "ranking item");
      ["score", "expected_source_protocol_normalized_margin_cluster_lcb",
        "worst_case_source_protocol_normalized_margin_cluster_lcb",
        "worst_case_source_protocol_success_rate_cluster_lcb",
        "worst_case_post_attack_ssim_cluster_lcb", "fidelity_score"]
        .forEach((key) => finiteUnit(item[key], `${item.model}.${key}`));
      if (typeof item.feasible !== "boolean" || typeof item.pareto_optimal !== "boolean"
        || !Array.isArray(item.constraint_violations)
        || item.constraint_violations.some((code) => !COLLABORATION_VIOLATIONS.includes(code))
        || item.feasible === Boolean(item.constraint_violations.length)
        || (!item.feasible && item.pareto_optimal)) fail(`${item.model} 可行性/约束结构无效`);
    });

    if (response.status === "constraint_unsatisfied" && response.recommendation === null) {
      fail("当前硬约束下不存在可选模型");
    }
    const recommendation = object(response.recommendation, "recommendation");
    if (response.status !== "recommendation_ready" || recommendation.model !== ranking[0].model
      || recommendation.feasible !== true || recommendation.pareto_optimal !== true
      || !Array.isArray(recommendation.low_risk_interaction_models)
      || recommendation.low_risk_interaction_models.some((model) => !MODEL_ORDER.includes(model))) {
      fail("协同推荐未指向首个可行 Pareto 候选");
    }
    approximately(stability.selected_model_frequency, frequencies[recommendation.model], "selected_model_frequency");

    const interactions = response.interaction_plan;
    if (!Array.isArray(interactions) || interactions.length !== 4) fail("交互计划未覆盖四种攻击者");
    exactKeys(Object.fromEntries(interactions.map((item) => [item.attacker_model, true])), MODEL_ORDER, "interaction attackers");
    interactions.forEach((item) => {
      if (item.source_model !== recommendation.model || !COLLABORATION_HINTS.includes(item.policy_hint)) {
        fail("交互计划来源或 planned policy hint 无效");
      }
      ["source_protocol_normalized_margin_cluster_lcb",
        "attacker_protocol_normalized_margin_cluster_lcb",
        "source_protocol_success_rate_cluster_lcb",
        "attacker_protocol_success_rate_cluster_lcb"]
        .forEach((key) => finiteUnit(item[key], `${item.attacker_model}.${key}`));
    });

    const ablation = object(response.ablation, "ablation");
    const legacy = object(ablation.legacy_iid_raw_accuracy, "legacy_iid_raw_accuracy");
    if (legacy.method !== "legacy_raw_bit_accuracy_iid_normal_wilson_diagnostic_only"
      || ablation.identity_cluster_normalized_policy_selected_model !== recommendation.model
      || ablation.selection_changed !== (legacy.selected_model !== recommendation.model)) {
      fail("新旧统计策略消融不可复核");
    }
    return { response, recommendation, ranking, interactions, scoring, evidence };
  }

  return Object.freeze({
    MODEL_ORDER,
    SIMSWAP_RUN_ID,
    validateCollaborationResponse,
    validateModelStatus,
    validateSimSwapEvidence,
  });
}));
