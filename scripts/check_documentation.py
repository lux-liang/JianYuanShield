from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system.backend.evidence import evidence_audit_payload  # noqa: E402


def main() -> int:
    files = {
        "competition": ROOT / "README_COMPETITION.md",
        "limitations": ROOT / "docs" / "LIMITATIONS.md",
        "judge_qa": ROOT / "docs" / "JUDGE_QA.md",
        "defense": ROOT / "docs" / "DEFENSE_SCRIPT_3MIN.md",
        "plan": ROOT / "docs" / "NEXT_14_DAYS_PLAN.md",
    }
    contents = {name: path.read_text(encoding="utf-8") if path.is_file() else "" for name, path in files.items()}
    audit = evidence_audit_payload()
    report_path = ROOT / "system" / "reports" / "jianyuanshield_competition_report" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    checks = {
        "all_documents_exist": all(path.is_file() for path in files.values()),
        "competition_claim_gate_current": (
            f"`ready_for_claims={'yes' if audit['ready_for_claims'] else 'no'}`" in contents["competition"]
        ),
        "judge_qa_mentions_signature": "Ed25519" in contents["judge_qa"],
        "judge_qa_mentions_kadnet_blocker": "没有 KAD-Net checkpoint" in contents["judge_qa"],
        "limitations_mentions_single_seed": "仅 1 seed" in contents["limitations"],
        "defense_separates_demo_and_claims": "研究结论状态仍为 review" in contents["defense"],
        "report_schema_current": report.get("schema_version") == "competition-report.v2",
        "report_gate_matches_api": (
            report.get("evidence_gate", {}).get("ready_for_demo") == audit.get("ready_for_demo")
            and report.get("evidence_gate", {}).get("ready_for_claims") == audit.get("ready_for_claims")
        ),
    }
    payload = {
        "schema_version": "documentation-check.v1",
        "status": "verified" if all(checks.values()) else "failed",
        "checks": checks,
        "files": {name: str(path) for name, path in files.items()},
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
