"""Prometheus metrics and webhook alerts."""

from __future__ import annotations

from typing import Any

try:
    import aiohttp
except ModuleNotFoundError:  # pragma: no cover - exercised only in stripped test envs
    aiohttp = None

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
except ModuleNotFoundError:  # pragma: no cover - exercised only in stripped test envs
    class _NoopMetric:
        def inc(self) -> None:
            return None

        def set(self, _value: float) -> None:
            return None

        def observe(self, _value: float) -> None:
            return None

    class CollectorRegistry:  # type: ignore[no-redef]
        def __init__(self, auto_describe: bool = True) -> None:
            self.auto_describe = auto_describe

    def Counter(*_args, **_kwargs):  # type: ignore[no-redef]
        return _NoopMetric()

    def Gauge(*_args, **_kwargs):  # type: ignore[no-redef]
        return _NoopMetric()

    def Histogram(*_args, **_kwargs):  # type: ignore[no-redef]
        return _NoopMetric()

    def start_http_server(*_args, **_kwargs) -> None:  # type: ignore[no-redef]
        return None

from app.config import MetricsConfig, WebhookConfig


class MetricsServer:
    """Expose process metrics and alerting hooks."""

    def __init__(
        self,
        config: MetricsConfig,
        webhook: WebhookConfig,
        registry: CollectorRegistry | None = None,
    ) -> None:
        self._config = config
        self._webhook = webhook
        self._registry = registry or CollectorRegistry(auto_describe=True)
        self._order_count = Counter("order_count", "Number of submitted orders", registry=self._registry)
        self._fill_count = Counter("fill_count", "Number of fills", registry=self._registry)
        self._signal_count = Counter("signal_count", "Number of strategy signals", registry=self._registry)
        self._pnl = Gauge("pnl_usd", "Current PnL", registry=self._registry)
        self._latency = Histogram("latency_ms", "Order round-trip latency in ms", registry=self._registry)
        self._kill_switch = Gauge("kill_switch_active", "Kill switch state", registry=self._registry)
        self._ws_reconnects = Gauge("ws_reconnect_count", "Websocket reconnect count", registry=self._registry)
        self._error_rate = Gauge("error_rate", "Errors per minute", registry=self._registry)
        self._reference_price = Gauge("reference_price", "Aggregated reference price", registry=self._registry)
        self._positions = Gauge("position_count", "Open position count", registry=self._registry)
        self._reconcile_discrepancies = Gauge(
            "reconcile_discrepancies",
            "Outstanding reconcile issues",
            registry=self._registry,
        )
        self._started = False

    @classmethod
    def from_defaults(cls) -> "MetricsServer":
        """Build an isolated in-memory metrics server for tests."""
        return cls(MetricsConfig(enabled=False), WebhookConfig(url=None), CollectorRegistry(auto_describe=True))

    def start(self) -> None:
        """Start the Prometheus HTTP endpoint."""
        if self._started:
            return
        start_http_server(self._config.port, addr=self._config.host, registry=self._registry)
        self._started = True

    def increment_order_count(self) -> None:
        """Increment order counter."""
        self._order_count.inc()

    def increment_fill_count(self) -> None:
        """Increment fill counter."""
        self._fill_count.inc()

    def increment_signal_count(self) -> None:
        """Increment signal counter."""
        self._signal_count.inc()

    def set_pnl(self, pnl: float) -> None:
        """Update PnL gauge."""
        self._pnl.set(pnl)

    def observe_latency(self, latency_ms: float) -> None:
        """Observe latency sample."""
        self._latency.observe(latency_ms)

    def set_kill_switch(self, active: bool, reason: str | None = None) -> None:
        """Set kill switch state and alert when activating."""
        self._kill_switch.set(1 if active else 0)
        if active:
            payload = {"reason": reason}
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                loop.create_task(self.send_alert("kill_switch", payload))
            except RuntimeError:
                pass

    def set_ws_reconnects(self, count: int) -> None:
        """Update websocket reconnect counter."""
        self._ws_reconnects.set(count)

    def set_error_rate(self, count: float) -> None:
        """Update error rate metric."""
        self._error_rate.set(count)

    def set_reference_price(self, price: float) -> None:
        """Update reference price gauge."""
        self._reference_price.set(price)

    def set_position_count(self, count: int) -> None:
        """Update open position count."""
        self._positions.set(count)

    def set_reconcile_discrepancies(self, count: int) -> None:
        """Update reconcile discrepancy count."""
        self._reconcile_discrepancies.set(count)

    async def send_alert(self, event: str, payload: dict[str, Any]) -> None:
        """Send a JSON alert to the configured webhook."""
        if not self._webhook.url:
            return
        if aiohttp is None:
            raise RuntimeError("aiohttp is required to send webhook alerts")
        body = {"event": event, "payload": payload}
        timeout = aiohttp.ClientTimeout(total=self._webhook.timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._webhook.url, json=body) as response:
                response.raise_for_status()
