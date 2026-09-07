"""Logging setup. Railway captures stdout, so everything goes there."""

from __future__ import annotations

import logging
import os
import sys


def setup(level: str | None = None) -> None:
    logging.basicConfig(
        level=(level or os.getenv("LOG_LEVEL", "INFO")).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # These libraries are chatty at INFO and drown out our own lines.
    for noisy in ("httpx", "httpcore", "openai", "hpack", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
