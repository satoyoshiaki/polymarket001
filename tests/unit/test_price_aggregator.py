"""Unit tests for price aggregation."""

from __future__ import annotations

from app.config import ExternalPriceConfig
from app.engines.price_aggregator import PriceAggregator
from app.models import PriceTick
from app.services.metrics_server import MetricsServer


def test_median_price_aggregation() -> None:
    metrics = MetricsServer.from_defaults()
    aggregator = PriceAggregator(ExternalPriceConfig(), metrics)
    import asyncio

    async def run() -> None:
        await aggregator.ingest(PriceTick(source="a", symbol="BTCUSDT", price=100, stale_after_ms=5_000))
        await aggregator.ingest(PriceTick(source="b", symbol="BTCUSDT", price=105, stale_after_ms=5_000))
        await aggregator.ingest(PriceTick(source="c", symbol="BTCUSDT", price=110, stale_after_ms=5_000))
        reference = await aggregator.reference_price()
        assert reference is not None
        assert reference.price == 105

    asyncio.run(run())


def test_trimmed_mean_for_small_samples() -> None:
    metrics = MetricsServer.from_defaults()
    aggregator = PriceAggregator(ExternalPriceConfig(), metrics)
    import asyncio

    async def run() -> None:
        await aggregator.ingest(PriceTick(source="a", symbol="BTCUSDT", price=100, stale_after_ms=5_000))
        await aggregator.ingest(PriceTick(source="b", symbol="BTCUSDT", price=110, stale_after_ms=5_000))
        reference = await aggregator.reference_price()
        assert reference is not None
        assert reference.price == 105

    asyncio.run(run())


def test_staleness_rejection() -> None:
    metrics = MetricsServer.from_defaults()
    aggregator = PriceAggregator(ExternalPriceConfig(), metrics)
    import asyncio

    async def run() -> None:
        stale_tick = PriceTick(source="a", symbol="BTCUSDT", price=100, stale_after_ms=-1)
        await aggregator.ingest(stale_tick)
        reference = await aggregator.reference_price()
        assert reference is None

    asyncio.run(run())
