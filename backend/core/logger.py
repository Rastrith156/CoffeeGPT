from __future__ import annotations

import sys

from loguru import logger

from core.config import settings


def setup_logger():
    settings.ensure_directories()
    logger.remove()

    console_level = "DEBUG" if settings.debug else settings.log_level
    logger.add(
        sys.stdout,
        level=console_level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
    )

    logger.add(
        settings.logs_root / "coffeegpt_{time:YYYY-MM-DD}.log",
        level="INFO",
        rotation="1 day",
        retention="30 days",
        compression="gz",
        serialize=True,
    )
    return logger
