from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


def setup_logging(log_file: Path, level: int = logging.INFO) -> logging.Logger:
    """
    Creates a dedicated application logger with file handler.
    GUI will receive log lines separately via worker signals.
    """
    logger = logging.getLogger("tpy_csv_gui")
    logger.setLevel(level)
    logger.propagate = False

    # Avoid duplicate handlers if setup is called multiple times.
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        return logger

    log_file.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
