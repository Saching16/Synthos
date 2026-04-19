"""Logging configuration (key=value lines, level from settings)."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging for the API process."""
    lvl = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="level=%(levelname)s time=%(asctime)s logger=%(name)s msg=%(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        ),
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(lvl)
