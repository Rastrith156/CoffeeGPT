"""
core/worker_supervisor.py
=========================
ISSUE #12 FIX: Production-grade worker supervision and lifecycle management.

Features:
  - Task registry and monitoring
  - Automatic restart with exponential backoff
  - Health check integration
  - Graceful coordinated shutdown
  - Failure tracking and circuit breaking
"""
from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core.errors import InitializationError, CircuitBreakerError
from core.logger import logger, bind_context


class WorkerTask:
    """Represents a supervised background task."""

    def __init__(
        self,
        name: str,
        coro_factory: Callable[[], Awaitable[None]],
        restart_on_failure: bool = True,
        max_restart_attempts: int = 5,
    ) -> None:
        self.name = name
        self.coro_factory = coro_factory
        self.restart_on_failure = restart_on_failure
        self.max_restart_attempts = max_restart_attempts
        
        self.task: asyncio.Task | None = None
        self.restart_count: int = 0
        self.failure_count: int = 0
        self.last_start: datetime | None = None
        self.last_failure: datetime | None = None
        self.status: str = "pending"  # pending, running, failed, stopped, circuit_broken

    def is_healthy(self) -> bool:
        """Check if task is running and healthy."""
        return self.task is not None and not self.task.done() and self.status == "running"

    def get_health_report(self) -> dict[str, Any]:
        """Get detailed health report for this task."""
        return {
            "name": self.name,
            "status": self.status,
            "restart_count": self.restart_count,
            "failure_count": self.failure_count,
            "last_start": self.last_start.isoformat() if self.last_start else None,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
            "is_healthy": self.is_healthy(),
        }


class WorkerSupervisor:
    """
    Production-grade worker supervisor with automatic restart, health monitoring,
    and graceful shutdown coordination.
    
    Usage:
        supervisor = WorkerSupervisor()
        supervisor.register_task("futures_stream", futures_stream.start)
        supervisor.register_task("market_monitor", market_monitor.start)
        await supervisor.start()
    """

    def __init__(
        self,
        restart_backoff_base: float = 2.0,
        restart_backoff_max: float = 60.0,
        circuit_breaker_threshold: int = 5,
    ) -> None:
        self._tasks: dict[str, WorkerTask] = {}
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._log = bind_context(component="worker_supervisor")
        
        # Restart configuration
        self._restart_backoff_base = restart_backoff_base
        self._restart_backoff_max = restart_backoff_max
        self._circuit_breaker_threshold = circuit_breaker_threshold
        
        # Monitoring
        self._supervisor_task: asyncio.Task | None = None
        self._health_check_interval = 10.0  # seconds

    def register_task(
        self,
        name: str,
        coro_factory: Callable[[], Awaitable[None]],
        restart_on_failure: bool = True,
        max_restart_attempts: int = 5,
    ) -> None:
        """Register a background task for supervision."""
        if name in self._tasks:
            raise InitializationError(
                f"Task '{name}' already registered",
                context={"task_name": name}
            )
        
        task = WorkerTask(
            name=name,
            coro_factory=coro_factory,
            restart_on_failure=restart_on_failure,
            max_restart_attempts=max_restart_attempts,
        )
        self._tasks[name] = task
        self._log.info("Registered supervised task: {}", name)

    async def start(self) -> None:
        """Start all registered tasks and begin supervision."""
        if self._running:
            self._log.warning("WorkerSupervisor already running")
            return

        self._running = True
        self._log.info("WorkerSupervisor starting with {} tasks", len(self._tasks))

        # Setup signal handlers
        self._setup_signal_handlers()

        # Start all tasks
        for task in self._tasks.values():
            await self._start_task(task)

        # Start supervision loop
        self._supervisor_task = asyncio.create_task(self._supervision_loop())

        # Wait for shutdown signal
        await self._shutdown_event.wait()
        await self._shutdown()

    async def stop(self) -> None:
        """Trigger graceful shutdown."""
        self._log.info("WorkerSupervisor shutdown requested")
        self._shutdown_event.set()

    def get_health_report(self) -> dict[str, Any]:
        """Get comprehensive health report for all tasks."""
        return {
            "supervisor_running": self._running,
            "total_tasks": len(self._tasks),
            "healthy_tasks": sum(1 for t in self._tasks.values() if t.is_healthy()),
            "failed_tasks": sum(1 for t in self._tasks.values() if t.status == "failed"),
            "circuit_broken_tasks": sum(1 for t in self._tasks.values() if t.status == "circuit_broken"),
            "tasks": {name: task.get_health_report() for name, task in self._tasks.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ─── Internal Methods ─────────────────────────────────────────────────────

    async def _start_task(self, worker_task: WorkerTask) -> None:
        """Start or restart a single task."""
        try:
            worker_task.task = asyncio.create_task(
                self._task_wrapper(worker_task),
                name=worker_task.name
            )
            worker_task.status = "running"
            worker_task.last_start = datetime.now(timezone.utc)
            self._log.info("Started task: {}", worker_task.name)
        except Exception as exc:
            worker_task.status = "failed"
            worker_task.failure_count += 1
            worker_task.last_failure = datetime.now(timezone.utc)
            self._log.error("Failed to start task {}: {}", worker_task.name, exc)

    async def _task_wrapper(self, worker_task: WorkerTask) -> None:
        """Wrapper that catches task exceptions and handles restart logic."""
        try:
            await worker_task.coro_factory()
        except asyncio.CancelledError:
            self._log.info("Task {} cancelled", worker_task.name)
            worker_task.status = "stopped"
            raise
        except Exception as exc:
            worker_task.failure_count += 1
            worker_task.last_failure = datetime.now(timezone.utc)
            self._log.error("Task {} failed: {}", worker_task.name, exc)
            
            if worker_task.restart_on_failure and self._running:
                await self._handle_task_failure(worker_task)
            else:
                worker_task.status = "failed"

    async def _handle_task_failure(self, worker_task: WorkerTask) -> None:
        """Handle task failure with restart logic and circuit breaking."""
        worker_task.restart_count += 1
        
        # Check circuit breaker
        if worker_task.restart_count >= self._circuit_breaker_threshold:
            worker_task.status = "circuit_broken"
            self._log.error(
                "Task {} circuit breaker tripped after {} restart attempts",
                worker_task.name,
                worker_task.restart_count
            )
            return
        
        # Check max restart attempts
        if worker_task.restart_count >= worker_task.max_restart_attempts:
            worker_task.status = "failed"
            self._log.error(
                "Task {} exceeded max restart attempts ({})",
                worker_task.name,
                worker_task.max_restart_attempts
            )
            return
        
        # Calculate backoff delay
        backoff = min(
            self._restart_backoff_base ** worker_task.restart_count,
            self._restart_backoff_max
        )
        
        self._log.info(
            "Restarting task {} in {:.1f}s (attempt {}/{})",
            worker_task.name,
            backoff,
            worker_task.restart_count,
            worker_task.max_restart_attempts
        )
        
        await asyncio.sleep(backoff)
        
        if self._running:
            await self._start_task(worker_task)

    async def _supervision_loop(self) -> None:
        """Periodic health check and monitoring loop."""
        self._log.info("Supervision loop started")
        
        while self._running:
            try:
                await asyncio.sleep(self._health_check_interval)
                
                # Check each task
                for task in self._tasks.values():
                    if task.task and task.task.done() and task.status == "running":
                        # Task completed unexpectedly
                        try:
                            # This will raise if task failed
                            task.task.result()
                            self._log.warning("Task {} completed unexpectedly", task.name)
                        except Exception as exc:
                            self._log.error("Task {} failed: {}", task.name, exc)
                        
                        if task.restart_on_failure and self._running:
                            await self._handle_task_failure(task)
                
                # Log health summary
                report = self.get_health_report()
                self._log.debug(
                    "Health check: {}/{} tasks healthy",
                    report["healthy_tasks"],
                    report["total_tasks"]
                )
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.error("Supervision loop error: {}", exc)

    async def _shutdown(self) -> None:
        """Gracefully shutdown all tasks."""
        self._running = False
        self._log.info("WorkerSupervisor shutting down...")
        
        # Cancel supervisor task
        if self._supervisor_task and not self._supervisor_task.done():
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all worker tasks
        tasks_to_cancel = []
        for worker_task in self._tasks.values():
            if worker_task.task and not worker_task.task.done():
                worker_task.task.cancel()
                tasks_to_cancel.append(worker_task.task)
        
        if tasks_to_cancel:
            self._log.info("Cancelling {} tasks...", len(tasks_to_cancel))
            results = await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            
            for worker_task, result in zip(self._tasks.values(), results):
                if isinstance(result, asyncio.CancelledError):
                    worker_task.status = "stopped"
                elif isinstance(result, Exception):
                    self._log.warning("Task {} shutdown error: {}", worker_task.name, result)
        
        self._log.info("WorkerSupervisor shutdown complete")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()
        
        def signal_handler():
            self._log.info("Received shutdown signal")
            asyncio.create_task(self.stop())
        
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, signal_handler)
            except NotImplementedError:
                # Signal handlers not supported on Windows in some contexts
                self._log.debug("Signal handler not supported for {}", sig)
