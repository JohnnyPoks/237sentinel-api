"""Structured, quiet-by-default logging.

Model load times are logged at INFO so cold-start behaviour is observable in
Space logs — the brief asks us to log load times.
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager

from app.config import settings


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers on reload.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
    )
    root.addHandler(handler)
    # Quiet noisy third parties.
    for noisy in ("httpx", "urllib3", "PIL", "easyocr"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def log_duration(logger: logging.Logger, what: str):
    """Log how long a block took — used for model loads and per-request timing."""
    start = time.perf_counter()
    logger.info("%s: starting", what)
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.info("%s: done in %.2fs", what, elapsed)
