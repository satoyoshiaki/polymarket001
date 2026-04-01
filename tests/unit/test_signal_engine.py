"""Unit tests for signal generation."""

from __future__ import annotations

from datetime import timedelta

from app.config import MarketDefinition, SignalConfig
from app.engines.signal_engine import SignalEngine
from app.models import MarketSnapshot, ReferencePrice, utc_now
from app.services.market_mapper import MarketMapper
from app.services.metrics_server import MetricsServer


def test_net_edge_calculation() -> None:
    metrics = MetricsServer.from_defaults()
    engine = SignalEngine(
        SignalConfig(
            default_size=1,
            taker_fee_estimate=0.01,
            slippage_estimate=0.01,
            execution_buffer=0.01,
            min_net_edge=0.01,
            probability_band=100,
        ),
        metrics,
    )
    mapper = MarketMapper([MarketDefinition(market_id="m1", description="x", strike_price=100)])
    snapshot = MarketSnapshot(market_id="m1", best_bid=0.40, best_ask=0.42)
    reference = ReferencePrice(symbol="BTCUSDT", price=200, contributors=["a"])
    signal = engine.build_signal(snapshot, reference, mapper)
    assert signal is not None
    assert round(signal.net_edge, 4) > 0.01


def test_threshold_gating() -> None:
    metrics = MetricsServer.from_defaults()
    engine = SignalEngine(
        SignalConfig(
            default_size=1,
            taker_fee_estimate=0.2,
            slippage_estimate=0.2,
            execution_buffer=0.2,
            min_net_edge=0.2,
            probability_band=100,
        ),
        metrics,
    )
    mapper = MarketMapper([MarketDefinition(market_id="m1", description="x", strike_price=100)])
    snapshot = MarketSnapshot(market_id="m1", best_bid=0.49, best_ask=0.51)
    reference = ReferencePrice(symbol="BTCUSDT", price=100, contributors=["a"])
    assert engine.build_signal(snapshot, reference, mapper) is None


def test_ttl_expiry() -> None:
    metrics = MetricsServer.from_defaults()
    engine = SignalEngine(SignalConfig(ttl_ms=1), metrics)
    mapper = MarketMapper([MarketDefinition(market_id="m1", description="x", strike_price=100)])
    snapshot = MarketSnapshot(market_id="m1", best_bid=0.10, best_ask=0.12)
    reference = ReferencePrice(symbol="BTCUSDT", price=1000, contributors=["a"])
    signal = engine.build_signal(snapshot, reference, mapper)
    assert signal is not None
    signal.timestamp = utc_now() - timedelta(milliseconds=10)
    assert signal.is_expired()

