"""Signal generation engine."""

from __future__ import annotations

from math import exp

from app.config import SignalConfig
from app.models import MarketSnapshot, ReferencePrice, Side, Signal, utc_now
from app.services.market_mapper import MarketMapper
from app.services.metrics_server import MetricsServer


class SignalEngine:
    """Convert market and reference prices into trading signals."""

    def __init__(self, config: SignalConfig, metrics: MetricsServer) -> None:
        self._config = config
        self._metrics = metrics

    def build_signal(
        self,
        snapshot: MarketSnapshot,
        reference_price: ReferencePrice,
        mapper: MarketMapper,
    ) -> Signal | None:
        """Return a signal when the net edge exceeds the configured threshold."""
        market = mapper.get_market(snapshot.market_id)
        if market is None:
            return None
        fair_yes = self._fair_probability(reference_price.price, market.strike_price)
        midpoint = snapshot.mid_price
        raw_edge_buy = fair_yes - midpoint
        raw_edge_sell = midpoint - fair_yes
        side = Side.BUY if raw_edge_buy >= raw_edge_sell else Side.SELL
        raw_edge = max(raw_edge_buy, raw_edge_sell)
        net_edge = (
            raw_edge
            - self._config.taker_fee_estimate
            - self._config.slippage_estimate
            - self._config.execution_buffer
        )
        if net_edge <= self._config.min_net_edge:
            return None
        signal = Signal(
            market_id=snapshot.market_id,
            side=side,
            size=self._config.default_size,
            raw_edge=raw_edge,
            net_edge=net_edge,
            ttl_ms=self._config.ttl_ms,
            timestamp=utc_now(),
        )
        self._metrics.increment_signal_count()
        return signal

    def _fair_probability(self, reference_price: float, strike_price: float) -> float:
        """Estimate binary fair value from spot vs strike."""
        scaled = (reference_price - strike_price) / max(self._config.probability_band, 1.0)
        return 1.0 / (1.0 + exp(-scaled))

