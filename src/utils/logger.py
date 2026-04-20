"""
Failure Logger
==============
Provides pre-configured file loggers that write to data/debug/logger/.
Each logger targets a specific failure domain.

Log files rotate daily and are kept for 7 days, then deleted automatically.
Terminal output (print statements) is unaffected — this is purely additive.

Usage:
    from src.utils.logger import get_logger

    log = get_logger("srs")
    log.error("delete_card failed for card %s: %s", card_id, e)

Available logger names and their output files:
    "srs"           → data/debug/logger/srs_fail.txt
    "questions"     → data/debug/logger/questions_gen_fail.txt
    "questions_raw" → data/debug/logger/questions_raw_fail.txt  (full raw LLM responses on parse failure)
    "cards"         → data/debug/logger/card_gen_fail.txt
    "course"        → data/debug/logger/course_gen_fail.txt
    "progress"      → data/debug/logger/progress_fail.txt
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOG_DIR = Path("data/debug/logger")
_RETENTION_DAYS = 7

_LOGGERS: dict[str, logging.Logger] = {}

_LOG_FILES = {
    "srs":            "srs_fail.txt",
    "questions":      "questions_gen_fail.txt",
    "questions_raw":  "questions_raw_fail.txt",
    "cards":          "card_gen_fail.txt",
    "course":         "course_gen_fail.txt",
    "progress":       "progress_fail.txt",
}

_FMT = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    """
    Return the named failure logger, creating it on first call.

    Args:
        name: One of "srs", "questions", "cards", "course", "progress".

    Returns:
        A configured Logger that writes to data/debug/<file>.
        Falls back to the root logger if the name is unrecognised.
    """
    if name in _LOGGERS:
        return _LOGGERS[name]

    if name not in _LOG_FILES:
        return logging.getLogger(name)

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"dml.{name}")
    logger.setLevel(logging.WARNING)
    logger.propagate = False  # don't bubble up to root logger

    handler = TimedRotatingFileHandler(
        filename=_LOG_DIR / _LOG_FILES[name],
        when="midnight",
        interval=1,
        backupCount=_RETENTION_DAYS,
        encoding="utf-8",
        delay=True,  # don't create the file until the first write
    )
    handler.setFormatter(_FMT)
    logger.addHandler(handler)

    _LOGGERS[name] = logger
    return logger
