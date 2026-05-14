"""
streaming/payloads.py
======================
Standardized typed message payloads for the Market Event Bus.
Ensures type safety and consistent schemas across broadcast channels.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FuturesUpdatePayload(BaseModel):
    """Payload for CHANNEL_FUTURES_UPDATED."""
    market: str = Field(..., description="arabica or robusta")
    symbol: str
    price: float
    change_percent: float
    volume: Optional[int] = None
    currency: str
    updated_at: datetime


class RiskChangePayload(BaseModel):
    """Payload for CHANNEL_RISK_CHANGED."""
    region: str
    overall_risk: str
    risks: List[Dict[str, Any]] = Field(..., description="List of specific risk signals")
    assessed_at: datetime


class AlertGeneratedPayload(BaseModel):
    """Payload for CHANNEL_ALERT_GENERATED."""
    type: str = Field(..., description="e.g., price_spike, weather_warning")
    market: Optional[str] = None
    region: Optional[str] = None
    severity: str = Field(..., description="low, medium, high")
    message: str
    timestamp: datetime


class WeatherAlertPayload(BaseModel):
    """Payload for CHANNEL_WEATHER_ALERT."""
    region: str
    event: str
    description: str
    severity: str
    timestamp: datetime
