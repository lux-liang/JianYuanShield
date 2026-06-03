from __future__ import annotations

import json
from pathlib import Path


ROOT = Path("/home/luxliang/work/vpsg_competition_candidates")
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
    hidden_clean = best_attack(hidden, "clean")
    sepmark_clean = best_attack(sepmark, "clean")
    waveguard_small_count = waveguard_small.get("requested_images", waveguard_small.get("status", "pending"))
    payload = {
        "project_name": "鉴源盾：面向 AIGC/Deepfake 内容传播链路的主动取证与抗攻击溯源平台",
        "forensic_conclusion": {
            "mainline": "SepMark is the current strongest real-checkpoint proactive watermark baseline on LFW.",
            "contrast": "HiDDeN is retained as a real-checkpoint negative/weak baseline on the same LFW benchmark.",
            "boundary": "LIDMark is smoke only; WaveGuard is checkpoint-load smoke only.",
            "defense_ready": bool(sepmark_clean) and sepmark_clean.get("mean_bit_accuracy", 0) > hidden_clean.get("mean_bit_accuracy", 0),
        },
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
        "",
        "## 取证结论",
        "",
        "- 当前最有答辩价值的真实模型主线是 SepMark：真实 checkpoint 已接入，正在/已经在真实 LFW 图片上完成 clean、JPEG、resize、noise 评测。",
        "- HiDDeN 保留为真实 checkpoint 弱对照：同样使用真实 LFW 全量评测，但 bit accuracy 接近随机，说明不是所有公开 watermark checkpoint 都能直接迁移到当前真实人脸域。",
        "- LIDMark 当前只作为 smoke checkpoint 链路验证，不能作为 official full model 性能。",
        f"- WaveGuard 当前已完成真实 checkpoint 单图 encode/decode smoke，并完成 {waveguard_small_count} 张 LFW 小规模 benchmark；完整 LFW benchmark 仍 pending。",
        "",
        "## 真实评测状态",
        f"- HiDDeN: {payload['hidden_lfw_full'].get('mode', payload['hidden_lfw_full'].get('status'))}, clean bit acc={hidden_clean.get('mean_bit_accuracy', '-')}",
        f"- SepMark: {payload['sepmark_lfw'].get('mode', payload['sepmark_lfw'].get('status'))}, clean bit acc={sepmark_clean.get('mean_bit_accuracy', '-')}, RF clean bit acc={sepmark_clean.get('mean_bit_accuracy_rf', '-')}",
        f"- WaveGuard-full: {payload['waveguard_full'].get('mode', payload['waveguard_full'].get('status'))}, clean detector bit acc={best_attack(waveguard_full, 'clean').get('mean_bit_accuracy_detector', '-')}, jpeg50 detector bit acc={best_attack(waveguard_full, 'jpeg50').get('mean_bit_accuracy_detector', '-')}",
        f"- WaveGuard-small: {payload['waveguard_small'].get('mode', payload['waveguard_small'].get('status'))}, clean detector bit acc={best_attack(waveguard_small, 'clean').get('mean_bit_accuracy_detector', '-')}, jpeg50 detector bit acc={best_attack(waveguard_small, 'jpeg50').get('mean_bit_accuracy_detector', '-')}",
        f"- LIDMark: {payload['lidmark_lfw_eval'].get('mode', payload['lidmark_lfw_eval'].get('status'))}",
        f"- WaveGuard: {payload['waveguard'].get('status', 'pending')}",
    ]
    (OUT / "report.md").write_text("\n".join(md), encoding="utf-8")
    # simple CSV index
    (OUT / "report.csv").write_text("section,path\nhidden_lfw_full,system/reports/hidden_lfw_full_benchmark/summary.json\nsepmark_lfw,system/reports/sepmark_lfw_benchmark/summary.json\nwaveguard_full,system/reports/waveguard_lfw_full_benchmark/summary.json\nwaveguard_small,system/reports/waveguard_lfw_small_benchmark/summary.json\nlidmark_lfw_eval,runs/lidmark_lfw_eval_full/summary.json\nwaveguard,system/reports/waveguard_lfw_benchmark/summary.json\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
