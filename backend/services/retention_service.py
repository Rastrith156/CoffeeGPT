"""
services/retention_service.py
==============================
Enterprise Data Retention Service.
Enforces cleanup rules:
  - Logs: 14 days
  - Raw RSS payloads: 30 days
  - Live ticks (if stored on disk): 7 days
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from core.config import settings
from core.logger import logger


class RetentionService:
    """
    Automated janitor service.
    Runs periodically to sweep away expired files and data blocks.
    """

    def __init__(self) -> None:
        self._logs_dir = settings.logs_root
        # Assuming raw data contains RSS and other payloads
        self._raw_data_dir = settings.raw_data_dir

    def _cleanup_dir(self, directory: Path, max_age_days: int, glob_pattern: str = "*") -> int:
        """Helper to delete files older than max_age_days."""
        if not directory.exists():
            return 0

        now = time.time()
        max_age_seconds = max_age_days * 86400
        deleted_count = 0

        try:
            for file_path in directory.glob(glob_pattern):
                if file_path.is_file():
                    file_age = now - os.path.getmtime(file_path)
                    if file_age > max_age_seconds:
                        file_path.unlink()
                        deleted_count += 1
                        logger.debug("Retention: Deleted expired file {}", file_path.name)
        except Exception as exc:
            logger.error("Retention failed during sweep of {}: {}", directory, exc)

        return deleted_count

    async def run_retention_sweep(self) -> None:
        """
        Execute a complete retention sweep across all storage tiers.
        Designed to be called by a background worker daily.
        """
        logger.info("Retention: Starting data cleanup sweep...")

        # 1. Clean logs (14 days)
        deleted_logs = self._cleanup_dir(self._logs_dir, max_age_days=14, glob_pattern="*.log*")

        # 2. Clean raw RSS/data payloads (30 days)
        # Assuming files are named like 'news_*.json' or similar
        deleted_raw = self._cleanup_dir(self._raw_data_dir, max_age_days=30, glob_pattern="*.json")

        # 3. Clean live ticks (7 days) if they produce files (e.g., tick_*.json)
        deleted_ticks = self._cleanup_dir(self._raw_data_dir, max_age_days=7, glob_pattern="tick_*.json")

        logger.info(
            "Retention sweep completed. Deleted: {} logs, {} raw payloads, {} tick files",
            deleted_logs,
            deleted_raw,
            deleted_ticks,
        )
