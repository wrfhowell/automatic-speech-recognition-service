"""PHI-safe logging setup.

Rule (§8.4): log jobId / chunkId / status / attempt counts only. Never log
transcript text or audio paths — paths can embed identifiers. Every log call
in this codebase goes through loggers configured here and is expected to
honor that rule; tests grep for violations.
"""

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
