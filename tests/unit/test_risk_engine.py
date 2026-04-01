"""Unit tests for risk controls."""

from __future__ import annotations

from datetime import timedelta

from app.config import RiskConfig
from app.engines.pnl_engine import PnLEngine
from app.engines.risk_engine import RiskEngine
from app.models import OrderRequest, Side, utc_now
from app.services.metrics_server import MetricsServer
from app.services.order_manager import OrderManager
from app.services.position_manager import PositionManager


def build_risk_engine(config: RiskConfig | None = None) -> RiskEngine:
    metrics = MetricsServer.from_defaults()
    order_manager = OrderManager(metrics)
    position_manager = PositionManager(metrics)
    pnl_engine = PnLEngine(config or RiskConfig(), metrics)
    return RiskEngine(config or RiskConfig(), order_manager, position_manager, pnl_engine, metrics)


def test_latency_kill_switch() -> None:
    risk = build_risk_engine(RiskConfig(latency_kill_switch_ms=100))
    risk.record_latency(150)
    assert risk.kill_switch_active
    assert risk.kill_reason == "latency"


def test_fill_ratio_kill_switch() -> None:
    risk = build_risk_engine(RiskConfig(min_fill_ratio=0.9))
    risk.record_order_submission(10)
    risk.record_fill(1)
    assert risk.kill_switch_active
    assert risk.kill_reason == "fill_ratio"


def test_ws_disconnect_kill_switch() -> None:
    risk = build_risk_engine(RiskConfig(ws_disconnect_kill_after_sec=1))
    risk._ws_last_seen = utc_now() - timedelta(seconds=5)  # noqa: SLF001
    decision = risk.evaluate_order(
        OrderRequest(
            market_id="m1",
            side=Side.BUY,
            size=1,
            price=1,
            order_type="FAK",
            client_order_id="abc",
        )
    )
    assert not decision.allowed
    assert decision.reason == "ws_disconnect"


def test_max_order_notional_pct() -> None:
    risk = build_risk_engine(RiskConfig(base_capital_usd=100, max_order_notional_pct=0.1))
    decision = risk.evaluate_order(
        OrderRequest(
            market_id="m1",
            side=Side.BUY,
            size=20,
            price=1,
            order_type="FAK",
            client_order_id="abc",
        )
    )
    assert not decision.allowed
    assert decision.reason == "max_order_notional_pct"

