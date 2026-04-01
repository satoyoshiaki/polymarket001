"""Integration test for paper trade flow."""

from __future__ import annotations

from app.config import MarketDefinition, PaperBrokerConfig, RiskConfig, SignalConfig
from app.engines.pnl_engine import PnLEngine
from app.engines.price_aggregator import PriceAggregator
from app.engines.risk_engine import RiskEngine
from app.engines.signal_engine import SignalEngine
from app.models import MarketSnapshot, PriceTick
from app.services.market_mapper import MarketMapper
from app.services.metrics_server import MetricsServer
from app.services.order_manager import OrderManager
from app.services.paper_broker import PaperBroker
from app.services.position_manager import PositionManager


def test_end_to_end_paper_trade_flow() -> None:
    metrics = MetricsServer.from_defaults()
    aggregator = PriceAggregator(
        config=type("Config", (), {"symbol": "BTCUSDT", "trim_ratio": 0.1})(),
        metrics=metrics,
    )
    order_manager = OrderManager(metrics)
    position_manager = PositionManager(metrics)
    pnl_engine = PnLEngine(RiskConfig(), metrics)
    risk_engine = RiskEngine(RiskConfig(), order_manager, position_manager, pnl_engine, metrics)
    signal_engine = SignalEngine(
        SignalConfig(
            default_size=1,
            taker_fee_estimate=0.01,
            slippage_estimate=0.0,
            execution_buffer=0.0,
            min_net_edge=0.02,
            probability_band=100,
        ),
        metrics,
    )
    broker = PaperBroker(PaperBrokerConfig(slippage_bps=0, fill_probability=1.0), order_manager, position_manager, metrics)
    mapper = MarketMapper([MarketDefinition(market_id="m1", description="market", strike_price=100)])

    import asyncio

    async def run() -> None:
        await aggregator.ingest(PriceTick(source="binance", symbol="BTCUSDT", price=200, stale_after_ms=5_000))
        reference = await aggregator.reference_price()
        assert reference is not None
        snapshot = MarketSnapshot(market_id="m1", best_bid=0.20, best_ask=0.22)
        signal = signal_engine.build_signal(snapshot, reference, mapper)
        assert signal is not None
        request = broker.build_order_request(signal, snapshot)
        decision = risk_engine.evaluate_order(request)
        assert decision.allowed
        await broker.submit_order(request, snapshot)
        assert order_manager.open_order_count() == 0
        assert position_manager.positions()["m1"].quantity == 1

    asyncio.run(run())
