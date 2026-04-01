"""Position tracking service."""

from __future__ import annotations

from app.models import FillEvent, Position
from app.services.metrics_server import MetricsServer


class PositionManager:
    """Track positions and realized PnL by market."""

    def __init__(self, metrics: MetricsServer) -> None:
        self._metrics = metrics
        self._positions: dict[str, Position] = {}

    def apply_fill(self, fill: FillEvent) -> float:
        """Apply a fill and return realized PnL."""
        position = self._positions.setdefault(fill.market_id, Position(market_id=fill.market_id))
        signed_size = fill.size if fill.side == "buy" else -fill.size
        realized = 0.0
        if position.quantity == 0 or position.quantity * signed_size > 0:
            new_abs_quantity = abs(position.quantity) + abs(signed_size)
            if new_abs_quantity > 0:
                weighted_cost = (position.average_price * abs(position.quantity)) + (fill.price * abs(signed_size))
                position.average_price = weighted_cost / new_abs_quantity
        else:
            closing_size = min(abs(position.quantity), abs(signed_size))
            direction = 1 if position.quantity > 0 else -1
            realized = (fill.price - position.average_price) * closing_size * direction
            position.realized_pnl += realized
            if abs(position.quantity) == abs(signed_size):
                position.average_price = 0.0
        position.quantity += signed_size
        self._metrics.set_position_count(len([p for p in self._positions.values() if p.quantity != 0]))
        return realized

    def positions(self) -> dict[str, Position]:
        """Return the current live positions."""
        return self._positions

    def market_exposure_notional(self, market_id: str) -> float:
        """Return current notional exposure for a market."""
        position = self._positions.get(market_id)
        if position is None:
            return 0.0
        return abs(position.quantity * position.average_price)

