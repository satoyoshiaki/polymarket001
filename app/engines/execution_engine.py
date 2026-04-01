"""Execution engine for paper, shadow, and live modes."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import structlog

from app.clients.external_price_client import ExternalPriceClient
from app.clients.market_data_client import MarketDataClient
from app.config import AppConfig
from app.models import MarketSnapshot, Mode, OrderRequest, OrderType, PriceTick, Side, Signal, TradeEvent
from app.services.market_mapper import MarketMapper
from app.services.metrics_server import MetricsServer
from app.services.order_manager import OrderManager
from app.services.paper_broker import PaperBroker
from app.services.position_manager import PositionManager
from app.services.reconciliation_service import ReconciliationService

try:
    from py_clob_client.client import ClobClient
except ImportError:  # pragma: no cover - exercised only when dependency missing
    ClobClient = None  # type: ignore[assignment]


class ExecutionEngine:
    """Route orders according to the configured mode."""

    def __init__(
        self,
        config: AppConfig,
        order_manager: OrderManager,
        position_manager: PositionManager,
        risk_engine,
        metrics: MetricsServer,
    ) -> None:
        self._config = config
        self._order_manager = order_manager
        self._position_manager = position_manager
        self._risk_engine = risk_engine
        self._metrics = metrics
        self._logger = structlog.get_logger(__name__)
        self._clob_client: Any | None = None
        if config.mode == Mode.GUARDED_LIVE and ClobClient is not None:
            # TODO: Verify exact py-clob-client constructor fields against the deployed API version.
            self._clob_client = ClobClient(
                host=config.polymarket.rest_url,
                key=config.polymarket.api_key.get_secret_value() if config.polymarket.api_key else None,
                chain_id=config.polymarket.chain_id,
                signature_type=2,
                funder=config.polymarket.funder_address,
            )

    async def run_forever(
        self,
        aggregator,
        signal_engine,
        paper_broker: PaperBroker,
        reconciliation: ReconciliationService,
        pnl_engine,
    ) -> None:
        """Run live market data and route resulting orders."""
        market_queue: asyncio.Queue[MarketSnapshot | TradeEvent] = asyncio.Queue()
        price_queue: asyncio.Queue[PriceTick] = asyncio.Queue()
        mapper = MarketMapper(self._config.markets)
        market_client = MarketDataClient(
            self._config.polymarket,
            mapper.market_ids(),
            market_queue,
        )
        external_client = ExternalPriceClient(self._config.external_prices, price_queue)

        tasks = [
            asyncio.create_task(market_client.run()),
            asyncio.create_task(external_client.run()),
            asyncio.create_task(reconciliation.run()),
            asyncio.create_task(self._consume_prices(aggregator, price_queue)),
            asyncio.create_task(
                self._consume_market_events(
                    aggregator,
                    signal_engine,
                    mapper,
                    market_queue,
                    paper_broker,
                    pnl_engine,
                    market_client,
                )
            ),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()

    async def _consume_prices(self, aggregator, price_queue: asyncio.Queue[PriceTick]) -> None:
        """Store external price ticks."""
        while True:
            tick = await price_queue.get()
            await aggregator.ingest(tick)

    async def _consume_market_events(
        self,
        aggregator,
        signal_engine,
        mapper: MarketMapper,
        market_queue: asyncio.Queue[MarketSnapshot | TradeEvent],
        paper_broker: PaperBroker,
        pnl_engine,
        market_client: MarketDataClient,
    ) -> None:
        """Process market events into signals and executions."""
        latest_snapshot: dict[str, MarketSnapshot] = {}
        while True:
            event = await market_queue.get()
            self._risk_engine.register_ws_heartbeat()
            self._metrics.set_ws_reconnects(market_client.reconnect_count)
            if isinstance(event, MarketSnapshot):
                latest_snapshot[event.market_id] = event
                reference = await aggregator.reference_price()
                if reference is None:
                    continue
                signal = signal_engine.build_signal(event, reference, mapper)
                if signal is None:
                    continue
                await self._handle_signal(signal, event, paper_broker)
                pnl_engine.mark_to_market(self._position_manager.positions(), latest_snapshot)

    async def _handle_signal(
        self,
        signal: Signal,
        snapshot: MarketSnapshot,
        paper_broker: PaperBroker,
    ) -> None:
        """Validate and route a signal."""
        if signal.is_expired():
            return
        price = snapshot.best_ask if signal.side == Side.BUY else snapshot.best_bid
        request = OrderRequest(
            market_id=signal.market_id,
            side=signal.side,
            size=signal.size,
            price=price,
            order_type=OrderType(self._config.execution.order_type),
            client_order_id=f"{signal.market_id}-{uuid.uuid4().hex[:16]}",
            expires_at=datetime.now(tz=UTC) + timedelta(milliseconds=signal.ttl_ms),
            metadata={"net_edge": signal.net_edge},
        )
        decision = self._risk_engine.evaluate_order(request)
        if not decision.allowed:
            self._logger.info("execution.signal_blocked", reason=decision.reason, market_id=signal.market_id)
            return
        self._risk_engine.record_order_submission(request.size)
        if self._config.mode == Mode.PAPER:
            await paper_broker.submit_order(request, snapshot)
            return
        if self._config.mode == Mode.SHADOW_LIVE:
            self._logger.info("execution.shadow_order", order=request.model_dump(mode="json"))
            await self._order_manager.record_shadow_order(request)
            return
        await self._submit_live_order(request)

    async def _submit_live_order(self, request: OrderRequest) -> None:
        """Submit a live order to the Polymarket CLOB."""
        if self._clob_client is None:
            raise RuntimeError("py-clob-client is required for guarded_live mode")
        self._order_manager.create_pending_order(request)
        for attempt in range(1, self._config.execution.retry_attempts + 1):
            start = time.perf_counter()
            try:
                signed_order = self._build_signed_order(request)
                response = await asyncio.to_thread(
                    self._clob_client.create_order,
                    signed_order,
                )
                latency_ms = (time.perf_counter() - start) * 1000.0
                self._risk_engine.record_latency(latency_ms)
                order_id = str(response.get("orderID") or response.get("id") or request.client_order_id)
                self._order_manager.mark_open(request.client_order_id, order_id)
                self._metrics.increment_order_count()
                return
            except (RuntimeError, ValueError, KeyError, TypeError, aiohttp.ClientError) as exc:
                self._risk_engine.record_error()
                if attempt == self._config.execution.retry_attempts:
                    self._order_manager.mark_rejected(request.client_order_id, str(exc))
                    raise
                await asyncio.sleep(self._config.execution.retry_backoff_sec * attempt)

    def _build_signed_order(self, request: OrderRequest) -> dict[str, Any]:
        """Build a signed order payload via py-clob-client."""
        if self._clob_client is None:
            raise RuntimeError("live client not initialized")
        order_args = {
            "token_id": request.market_id,
            "price": request.price,
            "size": request.size,
            "side": request.side.upper(),
            "expiration": int(request.expires_at.timestamp()) if request.expires_at else 0,
            "order_type": request.order_type,
            "client_order_id": request.client_order_id,
        }
        # TODO: Confirm order arg names against the exact py-clob-client release used in production.
        return self._clob_client.create_order_args(**order_args)
