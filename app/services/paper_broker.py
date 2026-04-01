"""Paper trading broker."""

from __future__ import annotations

import random
import uuid

from app.config import PaperBrokerConfig
from app.models import FillEvent, MarketSnapshot, OrderRequest, Side
from app.services.metrics_server import MetricsServer
from app.services.order_manager import OrderManager
from app.services.position_manager import PositionManager


class PaperBroker:
    """Simulate fills while preserving the live execution interface."""

    def __init__(
        self,
        config: PaperBrokerConfig,
        order_manager: OrderManager,
        position_manager: PositionManager,
        metrics: MetricsServer,
    ) -> None:
        self._config = config
        self._order_manager = order_manager
        self._position_manager = position_manager
        self._metrics = metrics
        self._fill_history: list[FillEvent] = []
        self._rng = random.Random(7)

    async def reset(self) -> None:
        """Reset paper state for a fresh backtest."""
        self._fill_history.clear()

    def build_order_request(self, signal, snapshot: MarketSnapshot) -> OrderRequest:
        """Build a paper order request from a signal."""
        price = snapshot.best_ask if signal.side == Side.BUY else snapshot.best_bid
        return OrderRequest(
            market_id=signal.market_id,
            side=signal.side,
            size=signal.size,
            price=price,
            order_type="FAK",
            client_order_id=f"paper-{uuid.uuid4().hex[:16]}",
            metadata={"net_edge": signal.net_edge},
        )

    async def submit_order(self, request: OrderRequest, snapshot: MarketSnapshot) -> FillEvent | None:
        """Simulate a fill and propagate the resulting events."""
        record = self._order_manager.create_pending_order(request)
        fill = self._simulate_fill(record.client_order_id, request, snapshot)
        if fill is None:
            return None
        self._order_manager.apply_fill(fill)
        self._position_manager.apply_fill(fill)
        self._fill_history.append(fill)
        self._metrics.increment_order_count()
        return fill

    def _simulate_fill(
        self,
        client_order_id: str,
        request: OrderRequest,
        snapshot: MarketSnapshot,
    ) -> FillEvent | None:
        """Simulate a probabilistic fill around the midpoint."""
        if self._rng.random() > self._config.fill_probability:
            return None
        slip = (self._config.slippage_bps / 10_000.0) * snapshot.mid_price
        price = snapshot.mid_price + slip if request.side == Side.BUY else snapshot.mid_price - slip
        return FillEvent(
            order_id=f"paper-fill-{uuid.uuid4().hex[:12]}",
            client_order_id=client_order_id,
            market_id=request.market_id,
            side=request.side,
            size=request.size,
            price=price,
        )

    def fill_history(self) -> list[FillEvent]:
        """Return fill history."""
        return self._fill_history

    def paper_positions(self):
        """Return paper positions."""
        return self._position_manager.positions()

    def realized_pnl(self) -> float:
        """Return aggregate realized PnL."""
        return sum(position.realized_pnl for position in self._position_manager.positions().values())

