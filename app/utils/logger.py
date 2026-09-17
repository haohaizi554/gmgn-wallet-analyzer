from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.utils.paths import LOG_DIR, ensure_runtime_dirs

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class QueueLogHandler(logging.Handler):
    """Forward log records to a callback (GUI log panel)."""

    def __init__(self, emit_fn) -> None:
        super().__init__()
        self.emit_fn = emit_fn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emit_fn(self.format(record), record.levelname)
        except Exception:
            self.handleError(record)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    ensure_runtime_dirs()
    logger = logging.getLogger("gmgn")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def get_logger(name: str = "gmgn") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logging.getLogger("gmgn").handlers:
        setup_logging()
    return logger


def attach_queue_handler(callback, logger_name: str = "gmgn") -> QueueLogHandler:
    logger = logging.getLogger(logger_name)
    for existing in list(logger.handlers):
        if isinstance(existing, QueueLogHandler):
            logger.removeHandler(existing)
    handler = QueueLogHandler(callback)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    return handler


def export_log_file() -> Path:
    return LOG_DIR / "app.log"
