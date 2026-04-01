"""State reconciliation against Polymarket REST."""

from __future__ import annotations

import asyncio

import aiohttp
import structlog

from app.config import AppConfig
from app.models import ReconcileResult
from app.services.metrics_server import MetricsServer
from app.services.order_manager import OrderManager
from app.services.position_manager import PositionManager


class ReconciliationService:
    """Periodically reconcile local state with remote state."""

    def __init__(
        self,
        config: AppConfig,
        order_manager: OrderManager,
        position_manager: PositionManager,
        metrics: MetricsServer,
    ) -> None:
        self._config = config
        self._order_manager = order_manager
        self._position_manager = position_manager
        self._metrics = metrics
        self._logger = structlog.get_logger(__name__)

    async def run(self) -> None:
        """Run reconciliation at the configured interval."""
        while True:
            try:
                result = await self.reconcile_once()
                if result.discrepancies:
                    self._logger.warning("reconcile.discrepancies", discrepancies=result.discrepancies)
                    await self._metrics.send_alert("reconcile_discrepancy", {"discrepancies": result.discrepancies})
            except (aiohttp.ClientError, ValueError, KeyError, TypeError) as exc:
                self._logger.warning("reconcile.failed", error=str(exc))
            await asyncio.sleep(self._config.execution.reconciliation_interval_sec)

    async def reconcile_once(self) -> ReconcileResult:
        """Fetch remote state and compare it with local state."""
        discrepancies: list[str] = []
        api_key = self._config.polymarket.api_key.get_secret_value() if self._config.polymarket.api_key else None
        if not api_key:
            return ReconcileResult(discrepancies=[])
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(f"{self._config.polymarket.rest_url}/data/orders") as response:
                response.raise_for_status()
                remote_orders = await response.json()
            remote_open = {
                str(item.get("client_order_id") or item.get("id"))
                for item in remote_orders
                if str(item.get("status", "")).lower() in {"open", "pending"}
            }
        local_open = {record.client_order_id for record in self._order_manager.open_orders()}
        for order_id in sorted(local_open - remote_open):
            discrepancies.append(f"local_open_missing_remote:{order_id}")
        for order_id in sorted(remote_open - local_open):
            discrepancies.append(f"remote_open_missing_local:{order_id}")
        self._metrics.set_reconcile_discrepancies(len(discrepancies))
        return ReconcileResult(discrepancies=discrepancies)

