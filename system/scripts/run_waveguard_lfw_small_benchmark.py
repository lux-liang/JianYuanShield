"""Compatibility entry point for the evidence-grade WaveGuard LFW benchmark.

The historical ``small`` runner used a reduced, non-canonical protocol.  The
entry point is retained for automation compatibility and now delegates to the
single auditable implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.scripts.run_waveguard_lfw_benchmark import main


if __name__ == "__main__":
    main()
