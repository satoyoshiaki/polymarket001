"""Application entrypoint and runtime wiring."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import structlog

from app.config import AppConfig, dumpable_config, load_config
from app.engines.backtest_engine import BacktestEngine
from app.engines.execution_engine import ExecutionEngine
from app.engines.pnl_engine import PnLEngine
from app.engines.price_aggregator import PriceAggregator
from app.engines.risk_engine import RiskEngine
from app.engines.signal_engine import SignalEngine
from app.logging_utils import configure_logging
from app.models import Mode
from app.services.metrics_server import MetricsServer
from app.services.order_manager import OrderManager
from app.services.paper_broker import PaperBroker
from app.services.position_manager import PositionManager
from app.services.reconciliation_service import ReconciliationService


async def run_app(config: AppConfig, backtest_file: str | None = None) -> None:
    """Run the requested application mode."""
    logger = structlog.get_logger(__name__)
    metrics = MetricsServer(config.metrics, config.webhook)
    order_manager = OrderManager(metrics)
    position_manager = PositionManager(metrics)
    pnl_engine = PnLEngine(config.risk, metrics)
    risk_engine = RiskEngine(config.risk, order_manager, position_manager, pnl_engine, metrics)
    aggregator = PriceAggregator(config.external_prices, metrics)
    signal_engine = SignalEngine(config.signal, metrics)

    if config.metrics.enabled:
        metrics.start()

    logger.info("app.start", config=dumpable_config(config))

    if config.mode == Mode.BACKTEST:
        if backtest_file is None:
            raise ValueError("backtest mode requires a backtest file")
        broker = PaperBroker(config.paper_broker, order_manager, position_manager, metrics)
        engine = BacktestEngine(
            config=config,
            price_aggregator=aggregator,
            signal_engine=signal_engine,
            risk_engine=risk_engine,
            broker=broker,
            pnl_engine=pnl_engine,
        )
        await engine.run(Path(backtest_file))
        return

    execution_engine = ExecutionEngine(config, order_manager, position_manager, risk_engine, metrics)
    paper_broker = PaperBroker(config.paper_broker, order_manager, position_manager, metrics)
    reconciliation = ReconciliationService(config, order_manager, position_manager, metrics)

    await execution_engine.run_forever(aggregator, signal_engine, paper_broker, reconciliation, pnl_engine)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Polymarket trading system")
    parser.add_argument(
        "--config",
        default="configs/paper.yaml",
        help="Path to YAML config",
    )
    parser.add_argument(
        "--backtest-file",
        default=None,
        help="Historical CSV/JSON file for backtests",
    )
    return parser.parse_args()


def main() -> None:
    """CLI wrapper for the application."""
    args = parse_args()
    config = load_config(args.config)
    configure_logging(config.log)
    asyncio.run(run_app(config, args.backtest_file))


if __name__ == "__main__":
    main()
