"""Logging setup."""

import logging
import sys

from src.shared.config import LOG_LEVEL


def get_logger(name: str) -> logging.Logger:
    """Get a named logger with standard formatting."""
    logger = logging.getLogger(f"pagefly.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    return logger
