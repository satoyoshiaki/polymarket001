"""Unit tests for the paper broker."""

from __future__ import annotations

from app.config import PaperBrokerConfig
from app.models import MarketSnapshot, OrderRequest, Side
from app.services.metrics_server import MetricsServer
from app.services.order_manager import OrderManager
from app.services.paper_broker import PaperBroker
from app.services.position_manager import PositionManager


def test_fill_simulation_and_position_tracking() -> None:
    metrics = MetricsServer.from_defaults()
    order_manager = OrderManager(metrics)
    position_manager = PositionManager(metrics)
    broker = PaperBroker(
        PaperBrokerConfig(slippage_bps=0, fill_probability=1.0),
        order_manager,
        position_manager,
        metrics,
    )
    request = OrderRequest(
        market_id="m1",
        side=Side.BUY,
        size=2,
        price=0.5,
        order_type="FAK",
        client_order_id="paper-1",
    )
    snapshot = MarketSnapshot(market_id="m1", best_bid=0.49, best_ask=0.51)
    import asyncio

    async def run() -> None:
        fill = await broker.submit_order(request, snapshot)
        assert fill is not None
        position = position_manager.positions()["m1"]
        assert position.quantity == 2
        assert position.average_price == 0.5

    asyncio.run(run())
