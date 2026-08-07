"""Compatibility entrypoint for the evidence-grade LIDMark benchmark.

The former four-attack/epoch-2 evaluator was not suitable for competition
claims.  Keeping this module as a thin entrypoint prevents legacy automation
from silently producing a second, weaker result schema.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.scripts.run_lidmark_lfw_benchmark import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
