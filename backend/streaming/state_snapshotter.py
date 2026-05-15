"""
streaming/state_snapshotter.py
================================
Hot-state snapshotter — periodically persists live Redis market state
to Postgres for durability and cold-start recovery.

Problem solved:
  Redis is volatile (in-memory). A Redis crash or restart loses all
  live market state, risk scores, and alert history that has not been
  persisted elsewhere.

Solution:
  • Every snapshot_interval_seconds: read `coffee:live:*` from Redis
    and write a snapshot row to `market_state_snapshots` Postgres table.
  • On cold-start: if Redis is empty (fresh boot), seed from the most
    recent Postgres snapshot to restore market continuity immediately.
  • Both Redis-unavailable and Postgres-unavailable cases are handled
    gracefully (log + skip, never crash the app).

Architecture:
    Redis (hot)  ──read──▶  StateSnapshotter  ──write──▶  Postgres (cold)
    Postgres     ──read──▶  StateSnapshotter  ──seed──▶   Redis (recovery)

Wire into core/runtime.py as an asyncio.Task (same pattern as MarketMonitor).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.logger import bind_context

# Late-import DB to avoid import-time errors when Postgres is unavailable
_DB_AVAILABLE: bool | None = None


class StateSnapshotter:
    """
    Periodic hot-state snapshot writer.

    Args:
        cache:  RedisMarketCache instance (or None → no-op).
        db:     SQLAlchemy Session factory or None → no-op.

    Call  start()  as an asyncio.Task.
    Call  seed_from_db()  at startup to restore Redis from Postgres.
    """

    def __init__(self, cache=None, db_factory=None) -> None:
        self._cache      = cache
        self._db_factory = db_factory
        self._running    = False
        self._log        = bind_context(stream_id="state_snapshotter")
        self._total_snapshots: int = 0

    # ── Background task ───────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        interval = settings.snapshot_interval_seconds
        self._log.info("StateSnapshotter started | interval={}s", interval)

        # Seed Redis from last Postgres snapshot on startup
        await self.seed_from_db()

        while self._running:
            await asyncio.sleep(interval)
            try:
                await self._snapshot_tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.warning("StateSnapshotter tick error: {}", exc)

    async def stop(self) -> None:
        self._running = False

    # ── Snapshot write ────────────────────────────────────────────────────────

    async def _snapshot_tick(self) -> None:
        """Read Redis hot state and write one snapshot row to Postgres."""
        if self._cache is None:
            return

        snapshot = await self._cache.get_live_snapshot()
        if not snapshot:
            return

        arabica  = snapshot.get("arabica") or {}
        robusta  = snapshot.get("robusta") or {}
        vol      = snapshot.get("volatility") or {}
        risk_raw = await self._cache.get_json("coffee:live:risk") or {}

        row: dict[str, Any] = {
            "arabica_price":    float(arabica.get("arabica_price") or 0),
            "arabica_change":   float(arabica.get("change_percent") or 0),
            "robusta_price":    float(robusta.get("robusta_price") or 0),
            "robusta_change":   float(robusta.get("change_percent") or 0),
            "arabica_vol_pct":  float(vol.get("arabica_volatility_pct") or 0),
            "robusta_vol_pct":  float(vol.get("robusta_volatility_pct") or 0),
            "risk_score":       float(risk_raw.get("risk_score") or 0),
            "risk_level":       str(risk_raw.get("risk_level") or "unknown"),
            "market_sentiment": str(
                (snapshot.get("market_state") or {}).get("market_sentiment") or "neutral"
            ),
            "snapshot_at":      datetime.now(timezone.utc),
        }

        success = await asyncio.to_thread(self._write_to_db, row)
        if success:
            self._total_snapshots += 1
            self._log.debug(
                "Snapshot written #{} | arabica={:.2f} robusta={:.2f} risk={:.0f}",
                self._total_snapshots, row["arabica_price"], row["robusta_price"], row["risk_score"],
            )

    def _write_to_db(self, row: dict[str, Any]) -> bool:
        """
        Synchronous Postgres write (runs in thread pool via asyncio.to_thread).
        Returns True on success, False on any error.
        """
        if self._db_factory is None:
            return False

        try:
            from models.market_snapshot_model import MarketStateSnapshot
            session = self._db_factory()
            try:
                snap = MarketStateSnapshot(**row)
                session.add(snap)
                session.commit()
                return True
            except Exception as exc:
                session.rollback()
                self._log.warning("Snapshot DB write failed: {}", exc)
                return False
            finally:
                session.close()
        except Exception as exc:
            self._log.warning("Snapshot DB factory error: {}", exc)
            return False

    # ── Cold-start recovery ───────────────────────────────────────────────────

    async def seed_from_db(self) -> None:
        """
        On startup: if Redis has no arabica price, load the most recent
        snapshot from Postgres and write it to Redis.

        This ensures zero-downtime Redis restarts don't cause a cold-start gap.
        """
        if self._cache is None or self._db_factory is None:
            return

        # Check if Redis already has data
        try:
            existing = await self._cache.get_arabica()
            if existing and float(existing.get("arabica_price") or 0) > 0:
                self._log.debug("Redis hot cache has existing data — skipping seed")
                return
        except Exception:
            pass

        row = await asyncio.to_thread(self._load_latest_snapshot)
        if row is None:
            self._log.debug("No Postgres snapshot found — starting with empty Redis hot cache")
            return

        try:
            if row["arabica_price"] > 0:
                await self._cache.update_arabica(
                    price=row["arabica_price"],
                    change_percent=row["arabica_change"],
                    volume=None,
                )
            if row["robusta_price"] > 0:
                await self._cache.update_robusta(
                    price=row["robusta_price"],
                    change_percent=row["robusta_change"],
                    volume=None,
                )
            self._log.info(
                "Redis seeded from Postgres snapshot | arabica={:.2f} robusta={:.2f}",
                row["arabica_price"], row["robusta_price"],
            )
        except Exception as exc:
            self._log.warning("Redis seed from Postgres failed: {}", exc)

    def _load_latest_snapshot(self) -> dict[str, Any] | None:
        if self._db_factory is None:
            return None
        try:
            from models.market_snapshot_model import MarketStateSnapshot
            session = self._db_factory()
            try:
                snap = (
                    session.query(MarketStateSnapshot)
                    .order_by(MarketStateSnapshot.snapshot_at.desc())
                    .first()
                )
                if snap is None:
                    return None
                return {
                    "arabica_price":  snap.arabica_price,
                    "arabica_change": snap.arabica_change,
                    "robusta_price":  snap.robusta_price,
                    "robusta_change": snap.robusta_change,
                    "risk_score":     snap.risk_score,
                    "risk_level":     snap.risk_level,
                }
            finally:
                session.close()
        except Exception as exc:
            self._log.warning("Snapshot DB load failed: {}", exc)
            return None
