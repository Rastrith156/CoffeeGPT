from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Any

try:
    from loguru import logger

    HAS_LOGURU = True
except ModuleNotFoundError:
    HAS_LOGURU = False

    class _FallbackLogger:
        def __init__(self) -> None:
            self._logger = logging.getLogger("coffeegpt")
            self._logger.setLevel(logging.DEBUG)
            self._logger.propagate = False

        def _format_message(self, message: str, *args) -> str:
            if not args:
                return message
            try:
                return message.format(*args)
            except Exception:
                return " ".join([message, *(str(arg) for arg in args)])

        def _log(self, level: int, message: str, *args, exc_info=False) -> None:
            self._logger.log(
                level,
                self._format_message(message, *args),
                exc_info=exc_info,
                stacklevel=3,
            )

        def debug(self, message: str, *args) -> None:
            self._log(logging.DEBUG, message, *args)

        def info(self, message: str, *args) -> None:
            self._log(logging.INFO, message, *args)

        def warning(self, message: str, *args) -> None:
            self._log(logging.WARNING, message, *args)

        def error(self, message: str, *args) -> None:
            self._log(logging.ERROR, message, *args)

        def critical(self, message: str, *args) -> None:
            self._log(logging.CRITICAL, message, *args)

        def exception(self, message: str, *args) -> None:
            self._log(logging.ERROR, message, *args, exc_info=True)

        def remove(self) -> None:
            for handler in list(self._logger.handlers):
                self._logger.removeHandler(handler)
                handler.close()

    logger: Any = _FallbackLogger()  # type: ignore[assignment]

from core.config import settings


def setup_logger():
    settings.ensure_directories()
    if HAS_LOGURU:
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

    logger.remove()

    console_level = logging.DEBUG if settings.debug else getattr(logging, settings.log_level.upper(), logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger._logger.addHandler(console_handler)

    file_handler = logging.FileHandler(
        settings.logs_root / f"coffeegpt_{datetime.now().strftime('%Y-%m-%d')}.log",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger._logger.addHandler(file_handler)
    return logger
