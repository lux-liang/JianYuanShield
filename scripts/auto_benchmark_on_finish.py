#!/usr/bin/env python3
"""Compatibility entrypoint for the frozen LIDMark evidence benchmark.

The former three-seed monitor targeted obsolete epoch/checkpoint layouts and
could launch several writers against one canonical report.  Checkpoint
selection is now performed once by ``select_lidmark_checkpoint.py`` and is
strictly revalidated by the benchmark itself.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from system.scripts.run_lidmark_lfw_benchmark import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
