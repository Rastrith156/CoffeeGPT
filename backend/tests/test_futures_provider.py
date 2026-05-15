"""
tests/test_futures_provider.py
================================
Tests for BarchartProvider and TickNormalizer.

All tests are fully offline — no HTTP requests, no Redis.
HTTP client is patched to return synthetic response fixtures.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from streaming.providers.barchart_provider import BarchartProvider, RawTickData
from streaming.normalizer import TickNormalizer, NormalisedTick


# ── TickNormalizer tests ──────────────────────────────────────────────────────

class TestTickNormalizer:

    def test_normalizes_arabica_raw(self):
        raw = RawTickData(
            market="arabica",
            source="barchart_live",
            raw={
                "symbol":        "KC",
                "lastPrice":     226.50,
                "netChange":     1.25,
                "percentChange": 0.55,
                "volume":        32000,
            },
        )
        n = TickNormalizer()
        tick = n.normalize(raw)
        assert tick is not None
        assert tick.market          == "arabica"
        assert tick.price           == pytest.approx(226.50)
        assert tick.change_percent  == pytest.approx(0.55)
        assert tick.volume          == 32000
        assert tick.currency        == "US cents/lb"
        assert tick.source          == "barchart_live"

    def test_normalizes_robusta_raw(self):
        raw = RawTickData(
            market="robusta",
            source="barchart_overview",
            raw={
                "symbol":        "RM",
                "lastPrice":     2390.0,
                "netChange":     0.0,
                "percentChange": 0.0,
                "volume":        None,
            },
        )
        tick = TickNormalizer().normalize(raw)
        assert tick is not None
        assert tick.market    == "robusta"
        assert tick.price     == pytest.approx(2390.0)
        assert tick.currency  == "USD/tonne"

    def test_returns_none_for_zero_price(self):
        raw = RawTickData(
            market="arabica",
            source="barchart_live",
            raw={"symbol": "KC", "lastPrice": 0.0, "netChange": 0.0, "percentChange": 0.0},
        )
        assert TickNormalizer().normalize(raw) is None

    def test_returns_none_for_unknown_market(self):
        raw = RawTickData(
            market="unknown_market",
            source="test",
            raw={"lastPrice": 100.0},
        )
        assert TickNormalizer().normalize(raw) is None

    def test_dual_key_in_to_dict(self):
        """to_dict() must expose both change_percent AND change_pct."""
        raw = RawTickData(
            market="arabica",
            source="synthetic",
            raw={
                "symbol":        "KC",
                "lastPrice":     220.0,
                "netChange":     2.0,
                "percentChange": 0.91,
                "volume":        None,
            },
        )
        d = TickNormalizer().normalize(raw).to_dict()
        assert "change_percent" in d
        assert "change_pct"     in d
        assert d["change_percent"] == d["change_pct"]

    def test_volatility_pct_derived(self):
        raw = RawTickData(
            market="arabica",
            source="synthetic",
            raw={
                "symbol":        "KC",
                "lastPrice":     220.0,
                "netChange":     4.4,
                "percentChange": 2.0,
                "volume":        None,
            },
        )
        tick = TickNormalizer().normalize(raw)
        assert tick is not None
        # volatility_factor = 0.5 → abs(2.0) * 0.5 = 1.0
        assert tick.volatility_pct == pytest.approx(1.0)

    def test_volume_none_passthrough(self):
        raw = RawTickData(
            market="arabica",
            source="synthetic",
            raw={"symbol": "KC", "lastPrice": 220.0, "netChange": 0.0, "percentChange": 0.0, "volume": None},
        )
        tick = TickNormalizer().normalize(raw)
        assert tick is not None
        assert tick.volume is None


# ── BarchartProvider synthetic fallback tests ─────────────────────────────────

class TestBarchartProviderSynthetic:

    def test_synthetic_arabica_returns_raw_tick(self):
        provider = BarchartProvider()
        raw = provider._synthetic_arabica()
        assert raw.market  == "arabica"
        assert raw.source  == "synthetic"
        assert raw.raw["lastPrice"] > 0

    def test_synthetic_robusta_returns_raw_tick(self):
        provider = BarchartProvider()
        raw = provider._synthetic_robusta()
        assert raw.market  == "robusta"
        assert raw.source  == "synthetic"
        assert raw.raw["lastPrice"] > 0

    def test_synthetic_state_updates_prev_price(self):
        provider = BarchartProvider()
        r1 = provider._synthetic_arabica()
        r2 = provider._synthetic_arabica()
        # _prev_arabica is stored at full float precision; r2.raw["lastPrice"] is rounded to 4dp.
        # Compare at the same rounded precision.
        assert round(provider._prev_arabica, 4) == pytest.approx(round(r2.raw["lastPrice"], 4))

    def test_synthetic_arabica_has_required_keys(self):
        raw = BarchartProvider()._synthetic_arabica()
        for key in ("symbol", "lastPrice", "netChange", "percentChange", "volume"):
            assert key in raw.raw, f"Missing key: {key}"


# ── BarchartProvider fetch with mocked HTTP ───────────────────────────────────

@pytest.fixture
def provider_with_mock_http():
    """BarchartProvider with a mock httpx.AsyncClient injected."""
    provider = BarchartProvider()
    mock_client = AsyncMock()
    provider._http = mock_client
    return provider, mock_client


@pytest.mark.asyncio
async def test_fetch_arabica_falls_back_to_synthetic_on_empty_results(provider_with_mock_http):
    provider, mock_client = provider_with_mock_http
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_client.get = AsyncMock(return_value=mock_resp)

    raw = await provider.fetch_arabica()
    # Empty results → synthetic fallback (in dev mode, settings.is_production=False)
    assert raw is not None
    assert raw.source == "synthetic"


@pytest.mark.asyncio
async def test_fetch_arabica_parses_live_quote():
    """Verify that a valid Barchart response is parsed into barchart_live source."""
    provider = BarchartProvider()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "results": [{
            "symbol":               "KC*1",
            "lastPrice":            228.75,
            "netChange":            1.10,
            "percentChange":        0.48,
            "volume":               41000,
            "previousOpenInterest": 85000,
        }]
    }
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    # Patch _get_client so we control the HTTP layer entirely
    with patch.object(provider, "_get_client", return_value=mock_client):
        raw = await provider.fetch_arabica()

    assert raw is not None
    assert raw.source             == "barchart_live"
    assert raw.raw["lastPrice"]   == pytest.approx(228.75)
    assert raw.raw["percentChange"] == pytest.approx(0.48)


@pytest.mark.asyncio
async def test_fetch_arabica_falls_back_on_exception(provider_with_mock_http):
    provider, mock_client = provider_with_mock_http
    mock_client.get = AsyncMock(side_effect=ConnectionError("timeout"))

    raw = await provider.fetch_arabica()
    # Exception → synthetic in dev
    assert raw is not None
    assert raw.source == "synthetic"
