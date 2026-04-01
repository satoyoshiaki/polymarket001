"""PnL aggregation engine."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

import structlog

from app.config import RiskConfig
from app.models import MarketSnapshot, Position
from app.services.metrics_server import MetricsServer


class PnLEngine:
    """Track hourly and daily PnL windows."""

    def __init__(self, config: RiskConfig, metrics: MetricsServer) -> None:
        self._config = config
        self._metrics = metrics
        self._logger = structlog.get_logger(__name__)
        self._realized_by_day: dict[str, float] = defaultdict(float)
        self._realized_by_hour: dict[str, float] = defaultdict(float)
        self._latest_unrealized = 0.0

    @property
    def daily_pnl(self) -> float:
        """Return current UTC-day PnL."""
        day_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        return self._realized_by_day[day_key] + self._latest_unrealized

    @property
    def hourly_pnl(self) -> float:
        """Return current UTC-hour PnL."""
        hour_key = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H")
        return self._realized_by_hour[hour_key] + self._latest_unrealized

    def record_realized(self, pnl: float) -> None:
        """Record realized PnL."""
        now = datetime.now(tz=UTC)
        self._realized_by_day[now.strftime("%Y-%m-%d")] += pnl
        self._realized_by_hour[now.strftime("%Y-%m-%dT%H")] += pnl
        self._metrics.set_pnl(self.daily_pnl)
        self._logger.info("pnl.realized", pnl=pnl, daily_pnl=self.daily_pnl, hourly_pnl=self.hourly_pnl)

    def mark_to_market(
        self,
        positions: dict[str, Position],
        snapshots: dict[str, MarketSnapshot],
    ) -> float:
        """Revalue open positions using the latest midpoint."""
        unrealized = 0.0
        for market_id, position in positions.items():
            snapshot = snapshots.get(market_id)
            if snapshot is None:
                continue
            position.unrealized_pnl = (snapshot.mid_price - position.average_price) * position.quantity
            unrealized += position.unrealized_pnl
        self._latest_unrealized = unrealized
        self._metrics.set_pnl(self.daily_pnl)
        return unrealized

