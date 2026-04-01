"""Runtime risk controls."""

from __future__ import annotations

from collections import deque
from datetime import timedelta

import structlog

from app.config import RiskConfig
from app.engines.pnl_engine import PnLEngine
from app.models import OrderRequest, RiskDecision, utc_now
from app.services.metrics_server import MetricsServer
from app.services.order_manager import OrderManager
from app.services.position_manager import PositionManager


class RiskEngine:
    """Evaluate whether a new order is allowed."""

    def __init__(
        self,
        config: RiskConfig,
        order_manager: OrderManager,
        position_manager: PositionManager,
        pnl_engine: PnLEngine,
        metrics: MetricsServer,
    ) -> None:
        self._config = config
        self._order_manager = order_manager
        self._position_manager = position_manager
        self._pnl_engine = pnl_engine
        self._metrics = metrics
        self._logger = structlog.get_logger(__name__)
        self._kill_switch_active = False
        self._kill_reason: str | None = None
        self._order_timestamps: deque = deque()
        self._cancel_timestamps: deque = deque()
        self._error_timestamps: deque = deque()
        self._latencies_ms: deque[float] = deque(maxlen=200)
        self._fills = 0.0
        self._submitted = 0.0
        self._ws_last_seen = utc_now()

    @property
    def kill_switch_active(self) -> bool:
        """Return current kill switch state."""
        return self._kill_switch_active

    @property
    def kill_reason(self) -> str | None:
        """Return the current kill switch reason."""
        return self._kill_reason

    def register_ws_heartbeat(self) -> None:
        """Update websocket last-seen timestamp."""
        self._ws_last_seen = utc_now()

    def record_order_submission(self, size: float) -> None:
        """Record a submitted order for rate and fill-ratio checks."""
        now = utc_now()
        self._order_timestamps.append(now)
        self._submitted += size
        self._evict_old(now)

    def record_cancel(self) -> None:
        """Record a cancellation event."""
        now = utc_now()
        self._cancel_timestamps.append(now)
        self._evict_old(now)

    def record_error(self) -> None:
        """Record an execution error."""
        now = utc_now()
        self._error_timestamps.append(now)
        self._evict_old(now)
        self._metrics.set_error_rate(float(len(self._error_timestamps)))
        if len(self._error_timestamps) > self._config.max_error_rate_per_min:
            self._activate_kill_switch("error_rate")

    def record_fill(self, size: float) -> None:
        """Record fills for fill-ratio checks."""
        self._fills += size
        if self.fill_ratio < self._config.min_fill_ratio and self._submitted >= 1.0:
            self._activate_kill_switch("fill_ratio")

    def record_latency(self, latency_ms: float) -> None:
        """Record observed round-trip latency."""
        self._latencies_ms.append(latency_ms)
        self._metrics.observe_latency(latency_ms)
        if latency_ms > self._config.latency_kill_switch_ms:
            self._activate_kill_switch("latency")

    @property
    def fill_ratio(self) -> float:
        """Return current fill ratio."""
        if self._submitted == 0:
            return 1.0
        return self._fills / self._submitted

    def evaluate_order(self, request: OrderRequest) -> RiskDecision:
        """Check whether an order is allowed under current limits."""
        now = utc_now()
        self._evict_old(now)
        self._check_loss_limits()
        self._check_ws_disconnect(now)
        if self._kill_switch_active:
            return RiskDecision(allowed=False, reason=self._kill_reason)

        capital = self._config.base_capital_usd
        order_notional = request.size * request.price
        if order_notional > capital * self._config.max_order_notional_pct:
            return RiskDecision(allowed=False, reason="max_order_notional_pct")
        if self._position_manager.market_exposure_notional(request.market_id) + order_notional > (
            capital * self._config.max_market_exposure_pct
        ):
            return RiskDecision(allowed=False, reason="max_market_exposure_pct")
        if self._order_manager.open_order_count() >= self._config.max_open_orders:
            return RiskDecision(allowed=False, reason="max_open_orders")
        if len(self._order_timestamps) >= self._config.max_orders_per_sec:
            return RiskDecision(allowed=False, reason="max_orders_per_sec")
        return RiskDecision(allowed=True)

    def evaluate_cancel(self) -> RiskDecision:
        """Check whether a cancel is allowed under rate limits."""
        now = utc_now()
        self._evict_old(now)
        if len(self._cancel_timestamps) >= self._config.max_cancel_per_sec:
            return RiskDecision(allowed=False, reason="max_cancel_per_sec")
        return RiskDecision(allowed=True)

    def _check_loss_limits(self) -> None:
        """Trigger kill switch on breached PnL thresholds."""
        capital = self._config.base_capital_usd
        if self._pnl_engine.daily_pnl <= -(capital * self._config.max_daily_loss_pct):
            self._activate_kill_switch("max_daily_loss_pct")
        if self._pnl_engine.hourly_pnl <= -(capital * self._config.max_hourly_loss_pct):
            self._activate_kill_switch("max_hourly_loss_pct")

    def _check_ws_disconnect(self, now) -> None:
        """Trigger kill switch on prolonged websocket disconnects."""
        if now - self._ws_last_seen > timedelta(seconds=self._config.ws_disconnect_kill_after_sec):
            self._activate_kill_switch("ws_disconnect")

    def _activate_kill_switch(self, reason: str) -> None:
        """Activate the kill switch and emit metrics."""
        if not self._kill_switch_active:
            self._logger.error("risk.kill_switch", reason=reason)
        self._kill_switch_active = True
        self._kill_reason = reason
        self._metrics.set_kill_switch(True, reason)

    def _evict_old(self, now) -> None:
        """Evict timestamps outside the rate-limit windows."""
        for queue, max_age in (
            (self._order_timestamps, 1.0),
            (self._cancel_timestamps, 1.0),
            (self._error_timestamps, 60.0),
        ):
            while queue and (now - queue[0]).total_seconds() > max_age:
                queue.popleft()
