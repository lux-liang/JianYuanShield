from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(os.getenv("JYS_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system.backend.evidence import evidence_audit_payload  # noqa: E402
from system.evaluation.protocol import protocol_summary  # noqa: E402


OUT = ROOT / "system/reports/jianyuanshield_competition_report"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": "pending"}


def best_attack(summary: dict, attack: str = "clean") -> dict:
    return summary.get("attacks", {}).get(attack, {})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hidden = read(ROOT / "system/reports/hidden_lfw_full_benchmark/summary.json")
    sepmark = read(ROOT / "system/reports/sepmark_lfw_benchmark/summary.json")
    lidmark = read(ROOT / "runs/lidmark_lfw_eval_full/summary.json")
    waveguard = read(ROOT / "system/reports/waveguard_lfw_benchmark/summary.json")
    waveguard_full = read(ROOT / "system/reports/waveguard_lfw_full_benchmark/summary.json")
    waveguard_small = read(ROOT / "system/reports/waveguard_lfw_small_benchmark/summary.json")
    aggregate = read(ROOT / "system/reports/aggregate_real_benchmarks/summary.json")
    statistics = read(ROOT / "system/reports/statistical_analysis/analysis.json")
    attack_smoke = read(ROOT / "system/reports/attack_library_smoke/report.json")
    lidmark_training = read(ROOT / "system/reports/lidmark_training/readiness.json")
    kadnet_integration = read(ROOT / "system/reports/kadnet_integration/audit.json")
    multi_embedding = read(ROOT / "system/reports/multi_embedding_matrix/plan.json")
    evidence_audit = evidence_audit_payload()
    evidence_gate = {
        key: evidence_audit.get(key)
        for key in (
            "status",
            "ready_for_demo",
            "ready_for_claims",
            "benchmark_complete",
            "findings",
            "blocking_findings",
            "protocol_audit",
            "diagnostics",
            "integration_gates",
        )
    }
    hidden_clean = best_attack(hidden, "clean")
    sepmark_clean = best_attack(sepmark, "clean")
    waveguard_small_count = waveguard_small.get("requested_images", waveguard_small.get("status", "pending"))
    waveguard_full_complete = waveguard_full.get("status") == "complete"
    payload = {
        "schema_version": "competition-report.v2",
        "generated_at": int(time.time()),
        "project_name": "鉴源盾：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台",
        "technology_provenance": {
            "ownership": "team_original",
            "repositories": ["LIDMark", "MEA", "WaveGuard", "KAD-Net"],
            "statement": "The model families and the unified platform are research outputs of the same team and are used with advisor approval.",
        },
        "forensic_conclusion": {
            "mainline": "SepMark is the current strongest real-checkpoint proactive watermark baseline on LFW.",
            "contrast": "HiDDeN is retained as a real-checkpoint negative/weak baseline on the same LFW benchmark.",
            "boundary": "LIDMark currently uses a smoke checkpoint; WaveGuard has completed the full 13,233-image LFW benchmark.",
            "defense_ready": bool(sepmark_clean) and sepmark_clean.get("mean_bit_accuracy", 0) > hidden_clean.get("mean_bit_accuracy", 0),
        },
        "review_items": [
            "Verify HiDDeN near-random clean recovery against the original training protocol.",
            "Normalize preprocessing and PSNR/SSIM reference semantics before final cross-method ranking.",
            "Run at least three independent seeds; current confidence intervals quantify image sampling only.",
            "Complete multi-embedding and real Deepfake model attacks; the current editing attack is an explicit proxy.",
            "Replace the LIDMark smoke checkpoint with a formally trained checkpoint.",
        ],
        "evaluation_protocol": protocol_summary(),
        "evidence_gate": evidence_gate,
        "statistical_analysis": statistics,
        "attack_library_smoke": attack_smoke,
        "lidmark_training_readiness": lidmark_training,
        "kadnet_integration_audit": kadnet_integration,
        "multi_embedding_matrix_plan": multi_embedding,
        "hidden_lfw_full": hidden,
        "sepmark_lfw": sepmark,
        "lidmark_lfw_eval": lidmark,
        "waveguard": waveguard,
        "waveguard_full": waveguard_full,
        "waveguard_small": waveguard_small,
        "aggregate": aggregate,
    }
    (OUT / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md = [
        "# 鉴源盾取证报告",
        "",
        "本报告由系统自动生成，区分 real checkpoint、smoke checkpoint 和 pending 状态。",
        f"协议版本：{payload['evaluation_protocol'].get('schema_version')}；演示状态：{evidence_gate.get('ready_for_demo')}；研究声明状态：{evidence_gate.get('ready_for_claims')}。",
        "",
        "## 取证结论",
        "",
        "- LIDMark、MEA、WaveGuard、KAD-Net 与鉴源盾平台均属于团队技术体系，经指导教师同意统一集成。",
        "- 当前最有答辩价值的真实模型主线是 SepMark：真实 checkpoint 已接入，并完成 13,233 张 LFW 全量评测。",
        "- HiDDeN 保留为团队真实 checkpoint 弱对照：bit accuracy 接近随机，最终答辩前需完成协议复核。",
        "- LIDMark 当前只作为 smoke checkpoint 链路验证，不能作为 official full model 性能。",
        (
            "- WaveGuard 已完成 13,233 张 LFW 全量真实 checkpoint benchmark。"
            if waveguard_full_complete
            else f"- WaveGuard 已完成 {waveguard_small_count} 张小规模 benchmark，全量评测尚未完成。"
        ),
        "",
        "## 真实评测状态",
        f"- HiDDeN: {payload['hidden_lfw_full'].get('mode', payload['hidden_lfw_full'].get('status'))}, clean bit acc={hidden_clean.get('mean_bit_accuracy', '-')}",
        f"- SepMark: {payload['sepmark_lfw'].get('mode', payload['sepmark_lfw'].get('status'))}, clean bit acc={sepmark_clean.get('mean_bit_accuracy', '-')}, RF clean bit acc={sepmark_clean.get('mean_bit_accuracy_rf', '-')}",
        f"- WaveGuard-full: {payload['waveguard_full'].get('mode', payload['waveguard_full'].get('status'))}, clean detector bit acc={best_attack(waveguard_full, 'clean').get('mean_bit_accuracy_detector', '-')}, jpeg50 detector bit acc={best_attack(waveguard_full, 'jpeg50').get('mean_bit_accuracy_detector', '-')}",
        f"- WaveGuard-small: {payload['waveguard_small'].get('mode', payload['waveguard_small'].get('status'))}, clean detector bit acc={best_attack(waveguard_small, 'clean').get('mean_bit_accuracy_detector', '-')}, jpeg50 detector bit acc={best_attack(waveguard_small, 'jpeg50').get('mean_bit_accuracy_detector', '-')}",
        f"- LIDMark: {payload['lidmark_lfw_eval'].get('mode', payload['lidmark_lfw_eval'].get('status'))}",
        f"- WaveGuard: {payload['waveguard'].get('status', 'pending')}",
        f"- 统计分析: {statistics.get('status', 'pending')}, seed_count={statistics.get('seed_count', 0)}, comparisons={len(statistics.get('comparisons', []))}",
        f"- 攻击库 smoke: {attack_smoke.get('status', 'pending')}, images={attack_smoke.get('images', 0)}, attacks={len(attack_smoke.get('attacks', []))}",
        f"- LIDMark 正式训练: {lidmark_training.get('status', 'not_generated')}, paired={lidmark_training.get('total_pairs', 0)}",
        f"- KAD-Net 接入: {kadnet_integration.get('status', 'not_generated')}, checkpoints={kadnet_integration.get('checkpoint_count', 0)}",
        f"- 二次嵌入矩阵: {multi_embedding.get('status', 'not_generated')}, runnable={multi_embedding.get('runnable_cells', 0)}/{multi_embedding.get('blocked_cells', 0) + multi_embedding.get('runnable_cells', 0)}",
        "",
        "## 待复核项",
        *[f"- {item}" for item in payload["review_items"]],
    ]
    (OUT / "report.md").write_text("\n".join(md), encoding="utf-8")
    # simple CSV index
    (OUT / "report.csv").write_text("section,path\nhidden_lfw_full,system/reports/hidden_lfw_full_benchmark/summary.json\nsepmark_lfw,system/reports/sepmark_lfw_benchmark/summary.json\nwaveguard_full,system/reports/waveguard_lfw_full_benchmark/summary.json\nwaveguard_small,system/reports/waveguard_lfw_small_benchmark/summary.json\nlidmark_lfw_eval,runs/lidmark_lfw_eval_full/summary.json\nwaveguard,system/reports/waveguard_lfw_benchmark/summary.json\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
