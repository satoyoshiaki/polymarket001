"""Historical backtest engine."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean, pstdev

import structlog

from app.models import MarketSnapshot, PriceTick
from app.services.market_mapper import MarketMapper


class BacktestEngine:
    """Replay historical events through the strategy stack."""

    def __init__(
        self,
        config,
        price_aggregator,
        signal_engine,
        risk_engine,
        broker,
        pnl_engine,
    ) -> None:
        self._config = config
        self._price_aggregator = price_aggregator
        self._signal_engine = signal_engine
        self._risk_engine = risk_engine
        self._broker = broker
        self._pnl_engine = pnl_engine
        self._logger = structlog.get_logger(__name__)

    async def run(self, path: Path) -> dict[str, float]:
        """Replay a CSV or JSON event file and return summary stats."""
        mapper = MarketMapper(self._config.markets)
        snapshots: dict[str, MarketSnapshot] = {}
        await self._broker.reset()
        for event in self._load_events(path):
            if isinstance(event, PriceTick):
                await self._price_aggregator.ingest(event)
                continue
            snapshots[event.market_id] = event
            reference = await self._price_aggregator.reference_price()
            if reference is None:
                continue
            signal = self._signal_engine.build_signal(event, reference, mapper)
            if signal is None:
                continue
            request = self._broker.build_order_request(signal, event)
            decision = self._risk_engine.evaluate_order(request)
            if not decision.allowed:
                continue
            self._risk_engine.record_order_submission(request.size)
            await self._broker.submit_order(request, event)
            self._pnl_engine.mark_to_market(self._broker.paper_positions(), snapshots)
        summary = self._summarize()
        self._logger.info("backtest.summary", **summary)
        return summary

    def _load_events(self, path: Path):
        """Yield typed events from a CSV or JSON file."""
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            for item in payload:
                yield self._event_from_mapping(item)
            return
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                yield self._event_from_mapping(row)

    def _event_from_mapping(self, payload: dict[str, str]):
        """Convert a raw mapping into an event."""
        event_type = payload["event_type"]
        if event_type == "price":
            return PriceTick(
                source=payload.get("source", "historical"),
                symbol=payload.get("symbol", "BTCUSDT"),
                price=float(payload["price"]),
                stale_after_ms=int(payload.get("stale_after_ms", 60_000)),
            )
        return MarketSnapshot(
            market_id=payload["market_id"],
            best_bid=float(payload["best_bid"]),
            best_ask=float(payload["best_ask"]),
            last_trade_price=float(payload["last_trade_price"]) if payload.get("last_trade_price") else None,
        )

    def _summarize(self) -> dict[str, float]:
        """Compute a simple backtest summary."""
        trades = self._broker.fill_history()
        realized_pnl = self._broker.realized_pnl()
        returns = [fill.size * (1 if fill.side == "sell" else -1) for fill in trades]
        win_rate = 0.0
        if trades:
            winning = sum(1 for fill in trades if fill.price >= 0.5)
            win_rate = winning / len(trades)
        sharpe = 0.0
        if len(returns) > 1 and pstdev(returns) > 0:
            sharpe = mean(returns) / pstdev(returns)
        return {
            "total_trades": float(len(trades)),
            "win_rate": win_rate,
            "net_pnl": realized_pnl,
            "sharpe_ratio_approx": sharpe,
        }

