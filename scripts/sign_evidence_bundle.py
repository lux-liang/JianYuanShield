from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system.backend.signing import generate_private_key, sign_evidence, verify_evidence_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify the JianYuanShield Ed25519 evidence bundle.")
    parser.add_argument("--private-key", type=Path, help="Private Ed25519 PEM used only for signing.")
    parser.add_argument("--generate-key", action="store_true", help="Create the private key if it does not exist.")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.verify_only:
        result = verify_evidence_bundle()
    else:
        if args.private_key is None:
            parser.error("--private-key is required for signing")
        if args.generate_key and not args.private_key.expanduser().exists():
            generate_private_key(args.private_key)
        result = sign_evidence(args.private_key)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
