from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


WatermarkModel = Literal["LIDMark", "KAD-Net", "SepMark", "WaveGuard"]


class DemoRunRequest(BaseModel):
    sample_id: str = Field(default="sample_face_001", pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    project: Literal["LIDMark", "SepMark", "WaveGuard", "KAD-Net"] = "LIDMark"
    attack: Literal["clean", "multi_embedding+jpeg_50+blur", "jpeg_50", "resize"] = (
        "multi_embedding+jpeg_50+blur"
    )


class CollaborationThreat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: WatermarkModel
    exposure: float = Field(
        strict=True,
        gt=0.0,
        le=1_000_000.0,
        allow_inf_nan=False,
    )


class CollaborationRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threats: list[CollaborationThreat] = Field(min_length=1, max_length=4)
    candidate_models: list[WatermarkModel] = Field(
        default_factory=lambda: ["LIDMark", "KAD-Net", "SepMark", "WaveGuard"],
        min_length=1,
        max_length=4,
    )
    risk_aversion: float | None = Field(
        default=None, strict=True, ge=0.0, le=1.0, allow_inf_nan=False
    )
    fidelity_weight: float | None = Field(
        default=None, strict=True, ge=0.0, le=1.0, allow_inf_nan=False
    )
    minimum_worst_case_protocol_normalized_margin: float | None = Field(
        default=None, strict=True, ge=0.0, le=1.0, allow_inf_nan=False
    )

    @field_validator("threats")
    @classmethod
    def unique_threat_models(
        cls, value: list[CollaborationThreat]
    ) -> list[CollaborationThreat]:
        models = [item.model for item in value]
        if len(models) != len(set(models)):
            raise ValueError("threats must not contain duplicate models")
        return value

    @field_validator("candidate_models")
    @classmethod
    def unique_candidate_models(cls, value: list[WatermarkModel]) -> list[WatermarkModel]:
        if len(value) != len(set(value)):
            raise ValueError("candidate_models must not contain duplicates")
        return value


CollaborationConstraintViolation = Literal[
    "worst_case_protocol_normalized_margin_cluster_lcb_below_floor",
    "worst_case_protocol_success_rate_cluster_lcb_below_floor",
    "worst_case_post_attack_psnr_cluster_lcb_below_floor",
    "worst_case_post_attack_ssim_cluster_lcb_below_floor",
]


class CollaborationRankingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: WatermarkModel
    feasible: bool
    constraint_violations: list[CollaborationConstraintViolation]
    score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    expected_source_bit_accuracy_diagnostic: float = Field(ge=0.0, le=1.0)
    worst_case_source_bit_accuracy_diagnostic: float = Field(ge=0.0, le=1.0)
    expected_source_protocol_normalized_margin: float = Field(ge=0.0, le=1.0)
    worst_case_source_protocol_normalized_margin: float = Field(ge=0.0, le=1.0)
    expected_source_protocol_normalized_margin_cluster_lcb: float = Field(
        ge=0.0, le=1.0
    )
    worst_case_source_protocol_normalized_margin_cluster_lcb: float = Field(
        ge=0.0, le=1.0
    )
    worst_case_source_protocol_success_rate_cluster_lcb: float = Field(
        ge=0.0, le=1.0
    )
    risk_adjusted_survival_cluster_lcb: float = Field(ge=0.0, le=1.0)
    initial_embedding_psnr_db: float = Field(ge=0.0, allow_inf_nan=False)
    expected_post_attack_psnr_db: float = Field(ge=0.0, allow_inf_nan=False)
    expected_post_attack_psnr_cluster_lcb_db: float = Field(
        ge=0.0, allow_inf_nan=False
    )
    worst_case_post_attack_psnr_cluster_lcb_db: float = Field(
        ge=0.0, allow_inf_nan=False
    )
    worst_case_post_attack_ssim_cluster_lcb: float = Field(ge=0.0, le=1.0)
    fidelity_score: float = Field(ge=0.0, le=1.0)
    pareto_optimal: bool


class CollaborationRecommendationItem(CollaborationRankingItem):
    low_risk_interaction_models: list[WatermarkModel]
    rationale_codes: list[
        Literal[
            "highest_feasible_confidence_adjusted_score",
            "content_addressed_mea_evidence",
            "feasible_domain_pareto_frontier",
            "identity_cluster_bootstrap_simultaneous_bounds",
            "protocol_normalized_cross_model_estimand",
        ]
    ]


class CollaborationInteractionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_model: WatermarkModel
    attacker_model: WatermarkModel
    threat_probability: float = Field(ge=0.0, le=1.0)
    class_: Literal[
        "coexistence",
        "source_dominant",
        "source_overwritten",
        "destructive_collision",
    ] = Field(alias="class", serialization_alias="class")
    policy_hint: Literal[
        "planned_dual_provenance_before_allow",
        "planned_reject_unverifiable_second_embedding",
        "planned_block_or_isolate_second_embedding",
        "planned_block_second_embedding",
    ]
    source_bit_accuracy_diagnostic: float = Field(ge=0.0, le=1.0)
    source_protocol_normalized_margin: float = Field(ge=0.0, le=1.0)
    source_protocol_normalized_margin_cluster_lcb: float = Field(ge=0.0, le=1.0)
    attacker_bit_accuracy_diagnostic: float = Field(ge=0.0, le=1.0)
    attacker_protocol_normalized_margin: float = Field(ge=0.0, le=1.0)
    attacker_protocol_normalized_margin_cluster_lcb: float = Field(ge=0.0, le=1.0)
    source_protocol_success_rate: float = Field(ge=0.0, le=1.0)
    source_protocol_success_rate_cluster_lcb: float = Field(ge=0.0, le=1.0)
    attacker_protocol_success_rate: float = Field(ge=0.0, le=1.0)
    attacker_protocol_success_rate_cluster_lcb: float = Field(ge=0.0, le=1.0)
    second_vs_original_psnr_db: float = Field(ge=0.0, allow_inf_nan=False)


class CollaborationRequestEcho(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threat_probabilities: dict[WatermarkModel, float]
    candidate_models: list[WatermarkModel] = Field(min_length=1, max_length=4)
    risk_aversion: float = Field(ge=0.0, le=1.0)
    fidelity_weight: float = Field(ge=0.0, le=1.0)
    minimum_worst_case_protocol_normalized_margin: float = Field(ge=0.0, le=1.0)


class CollaborationHardConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_worst_case_protocol_normalized_margin_cluster_lcb: float = Field(
        ge=0.0, le=1.0
    )
    minimum_worst_case_source_protocol_success_rate_cluster_lcb: float = Field(
        ge=0.0, le=1.0
    )
    minimum_worst_case_post_attack_psnr_cluster_lcb_db: float = Field(
        ge=0.0, allow_inf_nan=False
    )
    minimum_worst_case_post_attack_ssim_cluster_lcb: float = Field(
        ge=0.0, le=1.0
    )


class CollaborationModelSemantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_length: int = Field(gt=0)
    primary_decoder: str = Field(min_length=1)
    success_threshold: float = Field(gt=0.5, le=1.0)


class CollaborationSelectionStability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["cluster_resample_point_policy_selection_frequency"]
    resamples: int = Field(ge=128)
    selection_frequency: dict[str, float]
    selected_model_frequency: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_frequency_contract(self) -> "CollaborationSelectionStability":
        if set(self.selection_frequency) != {
            "LIDMark",
            "KAD-Net",
            "SepMark",
            "WaveGuard",
            "none",
        }:
            raise ValueError("selection stability must cover four models plus none")
        values = list(self.selection_frequency.values())
        if any(
            not math.isfinite(value) or value < 0.0 or value > 1.0
            for value in values
        ) or not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("selection stability frequencies must sum to one")
        return self


class CollaborationScoringResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence_level: float = Field(gt=0.5, lt=1.0)
    uncertainty_method: Literal["deterministic_identity_cluster_bootstrap_percentile"]
    cluster_key: Literal["lfw_filename_identity_prefix_v1"]
    estimand: Literal["equal_identity_weighted_mean_of_within_identity_image_means"]
    normalized_margin_transform: Literal[
        "piecewise_linear_protocol_threshold_centered_at_0_5"
    ]
    raw_bit_accuracy_use: Literal["diagnostic_only_not_cross_model_ranked"]
    bootstrap_rng: Literal["numpy_pcg64_multinomial"]
    bootstrap_seed: Literal[20260603]
    bootstrap_resamples: int = Field(ge=128)
    bootstrap_quantile_method: Literal["lower"]
    multiplicity_adjustment: Literal[
        "bonferroni_one_sided_fixed_full_selection_family"
    ]
    family_scope: Literal[
        "all_4_candidates_x_all_4_attackers_x_6_metrics_including_post_selection"
    ]
    family_metrics: list[
        Literal[
            "source_protocol_normalized_margin",
            "source_protocol_success",
            "attacker_protocol_normalized_margin",
            "attacker_protocol_success",
            "second_vs_original_psnr",
            "second_vs_original_ssim",
        ]
    ]
    family_size: Literal[96]
    per_comparison_alpha: float = Field(gt=0.0, lt=0.05)
    image_count: Literal[256]
    identity_count: Literal[217]
    repeated_identity_count: Literal[24]
    images_in_repeated_identities: Literal[63]
    max_cluster_size: Literal[10]
    model_semantics: dict[WatermarkModel, CollaborationModelSemantic]
    survival_formula: Literal[
        "(1-risk_aversion)*expected_normalized_margin_cluster_lcb+risk_aversion*worst_normalized_margin_cluster_lcb"
    ]
    fidelity_formula: Literal["normalize(expected_post_attack_psnr_cluster_lcb)"]
    overall_formula: Literal[
        "(1-fidelity_weight)*survival+fidelity_weight*fidelity"
    ]
    pareto_scope: Literal["hard_constraint_feasible_candidates_only"]
    pareto_dimensions: list[str]
    ranking_order: list[
        Literal[
            "feasible_first",
            "pareto_optimal_first",
            "score_descending",
            "fixed_model_order",
        ]
    ]
    tie_break_model_order: list[WatermarkModel]
    hard_constraints: CollaborationHardConstraints
    selection_stability: CollaborationSelectionStability

    @model_validator(mode="after")
    def validate_fixed_family_and_semantics(self) -> "CollaborationScoringResponse":
        if self.family_metrics != [
            "source_protocol_normalized_margin",
            "source_protocol_success",
            "attacker_protocol_normalized_margin",
            "attacker_protocol_success",
            "second_vs_original_psnr",
            "second_vs_original_ssim",
        ]:
            raise ValueError("bootstrap family metrics do not match the policy contract")
        if set(self.model_semantics) != {
            "LIDMark",
            "KAD-Net",
            "SepMark",
            "WaveGuard",
        }:
            raise ValueError("model semantics must cover the fixed four-model registry")
        expected_semantics = {
            "LIDMark": (16, "FHD_id_head", 0.9),
            "KAD-Net": (30, "ST_Decoder_C", 0.9),
            "SepMark": (128, "decoder_C", 0.9),
            "WaveGuard": (30, "tracer", 0.9),
        }
        if any(
            (
                self.model_semantics[model].message_length,
                self.model_semantics[model].primary_decoder,
                self.model_semantics[model].success_threshold,
            )
            != expected
            for model, expected in expected_semantics.items()
        ):
            raise ValueError("model semantics differ from the fixed protocol registry")
        return self


class CollaborationLegacyAblation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["legacy_raw_bit_accuracy_iid_normal_wilson_diagnostic_only"]
    selected_model: WatermarkModel | None
    feasible_models: list[WatermarkModel]


class CollaborationAblation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legacy_iid_raw_accuracy: CollaborationLegacyAblation
    identity_cluster_normalized_policy_selected_model: WatermarkModel | None
    selection_changed: bool


class CollaborationArtifactEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class CollaborationArtifactsEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_manifest: CollaborationArtifactEvidence
    raw_results: CollaborationArtifactEvidence
    run_config: CollaborationArtifactEvidence
    progress: CollaborationArtifactEvidence


class CollaborationReleaseSignature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: Literal[True]
    signer_pinned: Literal[True]
    profile: Literal["release-core", "release"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_key_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_path: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CollaborationEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_path: str
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_path: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_status: str | None
    source_claim_status: str | None
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    images_per_cell: int = Field(gt=0)
    image_count: Literal[256]
    identity_count: Literal[217]
    repeated_identity_count: Literal[24]
    images_in_repeated_identities: Literal[63]
    max_cluster_size: Literal[10]
    cells: Literal[16]
    rows: Literal[4096]
    artifacts: CollaborationArtifactsEvidence
    matrix_validation: dict[str, Any]
    release_signature: CollaborationReleaseSignature
    signature_verified: Literal[True]
    signer_pinned: Literal[True]
    content_verified: Literal[True]


class CollaborationRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["collaboration-recommendation.v2"]
    policy_id: str
    status: Literal["recommendation_ready", "constraint_unsatisfied"]
    recommendation: CollaborationRecommendationItem | None
    ranking: list[CollaborationRankingItem] = Field(min_length=1, max_length=4)
    interaction_plan: list[CollaborationInteractionItem] = Field(max_length=4)
    request: CollaborationRequestEcho
    scoring: CollaborationScoringResponse
    ablation: CollaborationAblation
    evidence: CollaborationEvidenceResponse

    @model_validator(mode="after")
    def validate_decision_invariants(self) -> "CollaborationRecommendationResponse":
        ranking_models = [item.model for item in self.ranking]
        if len(ranking_models) != len(set(ranking_models)):
            raise ValueError("ranking models must be unique")
        if len(self.request.candidate_models) != len(set(self.request.candidate_models)):
            raise ValueError("echoed candidate models must be unique")
        if set(ranking_models) != set(self.request.candidate_models):
            raise ValueError("ranking must cover the requested candidates exactly")
        if not self.request.threat_probabilities or any(
            not math.isfinite(probability) or probability <= 0.0 or probability > 1.0
            for probability in self.request.threat_probabilities.values()
        ):
            raise ValueError("threat probabilities must be finite and positive")
        if not math.isclose(
            sum(self.request.threat_probabilities.values()),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-7,
        ):
            raise ValueError("threat probabilities must sum to one")
        if self.evidence.release_signature.policy_sha256 != self.evidence.policy_sha256:
            raise ValueError("release signature must bind the returned policy hash")
        if (
            self.scoring.image_count != self.evidence.image_count
            or self.scoring.identity_count != self.evidence.identity_count
            or self.scoring.repeated_identity_count
            != self.evidence.repeated_identity_count
            or self.scoring.images_in_repeated_identities
            != self.evidence.images_in_repeated_identities
            or self.scoring.max_cluster_size != self.evidence.max_cluster_size
        ):
            raise ValueError("scoring and evidence identity audits differ")
        if (
            self.scoring.hard_constraints.minimum_worst_case_protocol_normalized_margin_cluster_lcb
            != self.request.minimum_worst_case_protocol_normalized_margin
        ):
            raise ValueError("request and applied normalized-margin constraints differ")
        if self.scoring.pareto_dimensions != [
            "expected_source_protocol_normalized_margin_cluster_lcb",
            "worst_case_source_protocol_success_rate_cluster_lcb",
            "fidelity_score",
        ]:
            raise ValueError("Pareto dimensions do not match the policy contract")
        if self.scoring.ranking_order != [
            "feasible_first",
            "pareto_optimal_first",
            "score_descending",
            "fixed_model_order",
        ] or self.scoring.tie_break_model_order != [
            "LIDMark",
            "KAD-Net",
            "SepMark",
            "WaveGuard",
        ]:
            raise ValueError("ranking and tie-break order do not match the policy contract")
        if any(item.feasible == bool(item.constraint_violations) for item in self.ranking):
            raise ValueError("ranking feasibility and violations disagree")
        if any(item.pareto_optimal for item in self.ranking if not item.feasible):
            raise ValueError("infeasible candidates cannot be Pareto optimal")
        new_selected = self.ablation.identity_cluster_normalized_policy_selected_model
        legacy_selected = self.ablation.legacy_iid_raw_accuracy.selected_model
        if self.ablation.selection_changed != (legacy_selected != new_selected):
            raise ValueError("ablation selection_changed is not reproducible")
        if self.status == "recommendation_ready":
            if self.recommendation is None or len(self.interaction_plan) != 4:
                raise ValueError("ready recommendation is incomplete")
            if (
                self.ranking[0].model != self.recommendation.model
                or not self.recommendation.feasible
                or not self.recommendation.pareto_optimal
            ):
                raise ValueError("selected recommendation is not the leading feasible Pareto row")
            if any(
                getattr(self.ranking[0], field) != getattr(self.recommendation, field)
                for field in CollaborationRankingItem.model_fields
            ):
                raise ValueError("recommendation metrics differ from the leading ranking row")
            if any(
                item.source_model != self.recommendation.model
                for item in self.interaction_plan
            ):
                raise ValueError("interaction plan source model mismatch")
            if new_selected != self.recommendation.model:
                raise ValueError("ablation selected model differs from recommendation")
            if not math.isclose(
                self.scoring.selection_stability.selected_model_frequency,
                self.scoring.selection_stability.selection_frequency[
                    self.recommendation.model
                ],
                rel_tol=0.0,
                abs_tol=1e-8,
            ):
                raise ValueError("selected-model stability frequency is inconsistent")
            if len(self.recommendation.low_risk_interaction_models) != len(
                set(self.recommendation.low_risk_interaction_models)
            ):
                raise ValueError("low-risk interaction models must be unique")
            if {item.attacker_model for item in self.interaction_plan} != {
                "LIDMark",
                "KAD-Net",
                "SepMark",
                "WaveGuard",
            }:
                raise ValueError("interaction plan must cover all four attackers")
        elif (
            self.recommendation is not None
            or self.interaction_plan
            or any(item.feasible for item in self.ranking)
            or new_selected is not None
        ):
            raise ValueError(
                "constraint-unsatisfied response must not contain a plan or feasible row"
            )
        return self
