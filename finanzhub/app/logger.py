"""Strukturiertes Logging für FinanzHub.

Stellt einen zentral konfigurierbaren Logger bereit. Schreibt standardmäßig
nach stderr; optional zusätzlich in eine Logdatei.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Final

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S%z"

_configured = False


def configure_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Initialisiert das Root-Logger-Setup. Idempotent."""
    global _configured
    if _configured:
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    handlers: list[logging.Handler] = []

    stream = logging.StreamHandler(stream=sys.stderr)
    stream.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    handlers.append(stream)

    if log_file:
        log_path = os.path.expanduser(log_file)
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        handlers.append(file_handler)

    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(numeric_level)

    # Drittanbieter-Logger auf INFO/WARNING drosseln, damit yfinance & Co. still sind.
    for noisy in ("yfinance", "peewee", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Liefert einen Kind-Logger. Initialisiert das Logging falls nötig."""
    if not _configured:
        level = os.environ.get("LOG_LEVEL", "INFO")
        log_file = os.environ.get("LOG_FILE") or None
        configure_logging(level=level, log_file=log_file)
    return logging.getLogger(name)
