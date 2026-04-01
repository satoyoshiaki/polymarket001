"""External price aggregation engine."""

from __future__ import annotations

import asyncio
from statistics import median

import structlog

from app.config import ExternalPriceConfig
from app.models import PriceTick, ReferencePrice, utc_now
from app.services.metrics_server import MetricsServer


class PriceAggregator:
    """Aggregate external prices into a reference price."""

    def __init__(self, config: ExternalPriceConfig, metrics: MetricsServer) -> None:
        self._config = config
        self._metrics = metrics
        self._logger = structlog.get_logger(__name__)
        self._latest: dict[str, PriceTick] = {}
        self._lock = asyncio.Lock()

    async def ingest(self, tick: PriceTick) -> None:
        """Store a new price tick."""
        async with self._lock:
            self._latest[tick.source] = tick

    async def reference_price(self) -> ReferencePrice | None:
        """Return the latest non-stale reference price."""
        async with self._lock:
            now = utc_now()
            valid_ticks = [tick for tick in self._latest.values() if not tick.is_stale(now)]
            if not valid_ticks:
                return None
            prices = sorted(tick.price for tick in valid_ticks)
            if len(prices) >= 3:
                reference = median(prices)
            else:
                reference = self._trimmed_mean(prices)
            result = ReferencePrice(
                symbol=self._config.symbol,
                price=reference,
                contributors=[tick.source for tick in valid_ticks],
                timestamp=now,
            )
            self._metrics.set_reference_price(reference)
            return result

    def _trimmed_mean(self, prices: list[float]) -> float:
        """Return a trimmed mean with a safe fallback for small samples."""
        if not prices:
            raise ValueError("prices must not be empty")
        if len(prices) < 3:
            return sum(prices) / len(prices)
        trim = max(1, int(len(prices) * self._config.trim_ratio))
        trimmed = prices[trim:-trim] or prices
        return sum(trimmed) / len(trimmed)

