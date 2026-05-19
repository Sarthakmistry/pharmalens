"""
agents/logger.py
Centralized logging configuration for PharmaLens.

Every agent module imports its logger from here:
    from agents.logger import get_logger
    logger = get_logger(__name__)

This ensures all loggers share the same handlers, format, and log directory
without each module setting up its own file handler.
"""

import logging
import logging.handlers
from pathlib import Path

try:
    _BASE_DIR = Path(__file__).parent.parent
except NameError:
    _BASE_DIR = Path.cwd().parent

LOG_DIR = _BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── root "pharmalens" logger — all child loggers inherit its handlers ──────────

_root_logger = logging.getLogger("pharmalens")

if not _root_logger.handlers:
    # guard prevents duplicate handlers if the module is reloaded in a notebook
    _root_logger.setLevel(logging.DEBUG)

    # file handler — rotating, 10 MB per file, 7 backups (~70 MB total)
    _file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "pharmalens.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=7,
        encoding="utf-8",
    )
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # console handler — INFO and above only to keep terminal output clean
    _console_handler = logging.StreamHandler()
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    ))

    _root_logger.addHandler(_file_handler)
    _root_logger.addHandler(_console_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the pharmalens namespace.

    Usage:
        from agents.logger import get_logger
        logger = get_logger(__name__)

    __name__ resolves to e.g. "agents.compiler", "agents.orchestrator",
    which Python automatically nests under the "pharmalens" root logger
    when prefixed correctly. If you pass __name__ directly, prefix it:

        logger = get_logger(f"pharmalens.{__name__}")

    Or pass the dotted name explicitly:

        logger = get_logger("pharmalens.compiler")
    """
    if not name.startswith("pharmalens"):
        name = f"pharmalens.{name}"
    return logging.getLogger(name)