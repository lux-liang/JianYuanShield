from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(os.getenv("JYS_PROJECT_ROOT", Path(__file__).resolve().parents[2])).expanduser().resolve()
MODEL_SOURCE_ROOT = Path(os.getenv("JYS_MODEL_SOURCE_ROOT", PROJECT_ROOT)).expanduser().resolve()
DATA_ROOT = Path(os.getenv("JYS_DATA_ROOT", PROJECT_ROOT / "datasets")).expanduser().resolve()
WEIGHT_ROOT = Path(os.getenv("JYS_WEIGHT_ROOT", PROJECT_ROOT / "weights")).expanduser().resolve()
REPORT_ROOT = Path(os.getenv("JYS_REPORT_ROOT", PROJECT_ROOT / "system" / "reports")).expanduser().resolve()
ASSET_ROOT = Path(os.getenv("JYS_ASSET_ROOT", PROJECT_ROOT / "system" / "assets")).expanduser().resolve()
