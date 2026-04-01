"""Order state manager."""

from __future__ import annotations

import uuid

from app.models import FillEvent, OrderRecord, OrderRequest, OrderState
from app.services.metrics_server import MetricsServer


class OrderManager:
    """Manage in-memory order lifecycle state and idempotency."""

    def __init__(self, metrics: MetricsServer) -> None:
        self._metrics = metrics
        self._orders_by_client_id: dict[str, OrderRecord] = {}
        self._orders_by_id: dict[str, OrderRecord] = {}

    def create_pending_order(self, request: OrderRequest) -> OrderRecord:
        """Create or return an idempotent pending order."""
        existing = self._orders_by_client_id.get(request.client_order_id)
        if existing is not None:
            return existing
        record = OrderRecord(
            order_id=f"pending-{uuid.uuid4().hex[:12]}",
            client_order_id=request.client_order_id,
            market_id=request.market_id,
            side=request.side,
            size=request.size,
            price=request.price,
            order_type=request.order_type,
            metadata=request.metadata,
        )
        self._orders_by_client_id[request.client_order_id] = record
        self._orders_by_id[record.order_id] = record
        return record

    async def record_shadow_order(self, request: OrderRequest) -> OrderRecord:
        """Record a shadow order without submission."""
        record = self.create_pending_order(request)
        record.state = OrderState.OPEN
        self._metrics.increment_order_count()
        return record

    def mark_open(self, client_order_id: str, order_id: str) -> OrderRecord:
        """Mark an order as open."""
        record = self._orders_by_client_id[client_order_id]
        self._orders_by_id.pop(record.order_id, None)
        record.order_id = order_id
        record.state = OrderState.OPEN
        self._orders_by_id[order_id] = record
        self._metrics.increment_order_count()
        return record

    def apply_fill(self, fill: FillEvent) -> OrderRecord:
        """Apply a fill to an order record."""
        record = self._orders_by_client_id[fill.client_order_id]
        record.filled_size += fill.size
        record.average_fill_price = fill.price
        record.state = OrderState.FILLED if record.filled_size >= record.size else OrderState.OPEN
        self._metrics.increment_fill_count()
        return record

    def mark_cancelled(self, client_order_id: str) -> OrderRecord:
        """Mark an order as cancelled."""
        record = self._orders_by_client_id[client_order_id]
        record.state = OrderState.CANCELLED
        return record

    def mark_rejected(self, client_order_id: str, reason: str) -> OrderRecord:
        """Mark an order as rejected."""
        record = self._orders_by_client_id[client_order_id]
        record.state = OrderState.REJECTED
        record.metadata["reject_reason"] = reason
        return record

    def open_order_count(self) -> int:
        """Return the number of pending/open orders."""
        return sum(
            1
            for record in self._orders_by_client_id.values()
            if record.state in {OrderState.PENDING, OrderState.OPEN}
        )

    def open_orders(self) -> list[OrderRecord]:
        """Return open or pending orders."""
        return [
            record
            for record in self._orders_by_client_id.values()
            if record.state in {OrderState.PENDING, OrderState.OPEN}
        ]

    def all_orders(self) -> list[OrderRecord]:
        """Return all orders."""
        return list(self._orders_by_client_id.values())

