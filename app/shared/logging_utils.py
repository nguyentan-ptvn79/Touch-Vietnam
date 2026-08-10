from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    root_logger = logging.getLogger()
    if getattr(configure_logging, "_configured", False):
        return

    log_level = getattr(logging, settings.log_level, logging.INFO)
    root_logger.setLevel(log_level)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        settings.log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logging.getLogger("werkzeug").setLevel(log_level)
    configure_logging._configured = True
