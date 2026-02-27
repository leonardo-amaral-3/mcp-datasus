"""Structured logging setup."""

import logging
import sys

from ..config import LOG_LEVEL


def get_logger(name: str) -> logging.Logger:
    """Cria logger com formato estruturado para o modulo."""
    logger = logging.getLogger(f"manual_sih_rag.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, LOG_LEVEL, logging.WARNING))
    return logger
