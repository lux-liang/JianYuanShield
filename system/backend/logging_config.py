from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import REPORTS
from .settings import settings


LOG_DIR = REPORTS / "_logs"
LOG_FILE = LOG_DIR / "backend.log"
LOGGER_NAME = "jianyuanshield.backend"


def configure_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Keep stdout available for machine-readable command output (for example,
    # JSON emitted by deployment probes); operational logs belong on stderr.
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = configure_logging()
