"""Rotating file logs in the data directory, for every environment. NSSM (or the scheduled
task wrapper) captures stdout separately; this is the log a person reads first."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# The root logger covers every ``app.*`` logger; uvicorn's two roots do not propagate to it.
LOGGERS = ("", "uvicorn", "uvicorn.access")
_configured: set[Path] = set()


def configure_logging(log_dir: Path, level: str = "INFO") -> Path:
    """Attach a 10 MB × 10 rotating file handler to the root and uvicorn loggers (once)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "mf-analyser.log"
    if path in _configured:
        return path
    handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(level)
    for name in LOGGERS:
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        if logger.level == logging.NOTSET or logger.level > logging.getLevelName(level):
            logger.setLevel(level)
    _configured.add(path)
    return path
