"""
worker.py
=========
Standalone Asyncio Worker Process.
Decouples ingestion, streaming, and monitoring loops from the FastAPI process.
"""
from __future__ import annotations

import asyncio
import signal
import sys
from core.config import settings
from core.logger import logger, setup_logger

# Import services that need to run in the background
from streaming.futures_stream import FuturesStreamService
from services.retention_service import RetentionService
# Assuming these exist or will be adapted
# from streaming.market_monitor import MarketMonitor
# from agents.intelligence_loop import IntelligenceLoop


class BackgroundWorker:
    """
    Orchestrates all background tasks in a separate process.
    """

    def __init__(self) -> None:
        self.futures_stream = FuturesStreamService()
        self.retention_service = RetentionService()
        self._running = False

    async def start(self) -> None:
        """Start all background loops."""
        self._running = True
        logger.info("Background Worker starting up...")

        # Create tasks for all background services
        tasks = [
            asyncio.create_task(self.futures_stream.start()),
            asyncio.create_task(self._run_retention_loop()),
            # asyncio.create_task(self.market_monitor.start()),
            # asyncio.create_task(self.intelligence_loop.start()),
        ]

        logger.info("All background tasks registered. Running...")

        try:
            # Wait for all tasks to run
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled. Shutting down...")
        except Exception as exc:
            logger.error("Worker error: {}", exc)
        finally:
            await self.stop()

    async def _run_retention_loop(self) -> None:
        """Runs the retention sweep once a day."""
        while self._running:
            try:
                await self.retention_service.run_retention_sweep()
            except Exception as exc:
                logger.error("Retention sweep failed: {}", exc)
            # Sleep for 24 hours
            await asyncio.sleep(86400)

    async def stop(self) -> None:
        """Stop all services."""
        self._running = False
        logger.info("Stopping background worker...")
        await self.futures_stream.stop()
        # Cancel any remaining tasks if needed


async def main() -> None:
    # Setup logging for the worker process
    setup_logger()

    worker = BackgroundWorker()

    # Handle termination signals
    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received shutdown signal.")
        asyncio.create_task(worker.stop())
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Signal handlers not supported on Windows in some contexts, but usually fine in get_running_loop()
            pass

    try:
        await worker.start()
    except Exception as exc:
        logger.critical("Worker failed to start: {}", exc)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
