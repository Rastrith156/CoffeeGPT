"""
models/market_snapshot_model.py
=================================
SQLAlchemy model for persistent hot-state snapshots.

Each row represents one point-in-time snapshot of the full
live market state, written by StateSnapshotter every N minutes.

Table: market_state_snapshots
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class MarketStateSnapshot(Base):
    """
    One snapshot of the live market state at a given point in time.

    Created by streaming.state_snapshotter.StateSnapshotter.
    Used for:
      • Redis cold-start recovery (seed from latest row)
      • Historical market state analysis
      • Audit trail for risk and alert states
    """
    __tablename__ = "market_state_snapshots"

    id               = Column(Integer, primary_key=True, autoincrement=True)

    # ── Price data ────────────────────────────────────────────────────────────
    arabica_price    = Column(Float, nullable=False, default=0.0)
    arabica_change   = Column(Float, nullable=False, default=0.0)
    robusta_price    = Column(Float, nullable=False, default=0.0)
    robusta_change   = Column(Float, nullable=False, default=0.0)

    # ── Volatility ────────────────────────────────────────────────────────────
    arabica_vol_pct  = Column(Float, nullable=False, default=0.0)
    robusta_vol_pct  = Column(Float, nullable=False, default=0.0)

    # ── Risk ──────────────────────────────────────────────────────────────────
    risk_score       = Column(Float, nullable=False, default=0.0)
    risk_level       = Column(String(16), nullable=False, default="unknown")

    # ── Sentiment ─────────────────────────────────────────────────────────────
    market_sentiment = Column(String(32), nullable=False, default="neutral")

    # ── Timestamp ─────────────────────────────────────────────────────────────
    snapshot_at      = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<MarketStateSnapshot id={self.id} "
            f"arabica={self.arabica_price:.2f} robusta={self.robusta_price:.2f} "
            f"risk={self.risk_score:.0f}/{self.risk_level} at={self.snapshot_at}>"
        )

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "arabica_price":    self.arabica_price,
            "arabica_change":   self.arabica_change,
            "robusta_price":    self.robusta_price,
            "robusta_change":   self.robusta_change,
            "arabica_vol_pct":  self.arabica_vol_pct,
            "robusta_vol_pct":  self.robusta_vol_pct,
            "risk_score":       self.risk_score,
            "risk_level":       self.risk_level,
            "market_sentiment": self.market_sentiment,
            "snapshot_at":      self.snapshot_at.isoformat() if self.snapshot_at else None,
        }
