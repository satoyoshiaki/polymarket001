"""External BTC price feed client."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import structlog

from app.config import ExternalPriceConfig
from app.models import PriceTick


class ExternalPriceClient:
    """Collect external BTC prices from multiple sources."""

    def __init__(self, config: ExternalPriceConfig, event_queue: asyncio.Queue[PriceTick]) -> None:
        self._config = config
        self._event_queue = event_queue
        self._logger = structlog.get_logger(__name__)

    async def run(self) -> None:
        """Run all source loops concurrently."""
        async with aiohttp.ClientSession() as session:
            tasks = []
            if self._config.binance.enabled:
                tasks.append(asyncio.create_task(self._run_binance(session)))
            if self._config.coingecko.enabled:
                tasks.append(asyncio.create_task(self._run_coingecko(session)))
            await asyncio.gather(*tasks)

    async def _run_binance(self, session: aiohttp.ClientSession) -> None:
        """Run Binance websocket with REST fallback."""
        backoff = 1.0
        while True:
            try:
                assert self._config.binance.websocket_url is not None
                async with session.ws_connect(self._config.binance.websocket_url, heartbeat=20) as websocket:
                    self._logger.info("external.binance_connected")
                    backoff = 1.0
                    async for message in websocket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(message.data)
                            price = float(payload["p"])
                            await self._event_queue.put(
                                PriceTick(
                                    source="binance",
                                    symbol=self._config.symbol,
                                    price=price,
                                    stale_after_ms=self._config.binance.stale_after_ms,
                                )
                            )
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            raise aiohttp.ClientError("Binance websocket error")
            except (aiohttp.ClientError, AssertionError, KeyError, ValueError, TypeError) as exc:
                self._logger.warning("external.binance_error", error=str(exc), backoff=backoff)
                await self._run_binance_rest_once(session)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
            except asyncio.CancelledError:
                raise

    async def _run_binance_rest_once(self, session: aiohttp.ClientSession) -> None:
        """Fetch one REST price tick from Binance."""
        if not self._config.binance.rest_url:
            return
        async with session.get(self._config.binance.rest_url) as response:
            response.raise_for_status()
            payload = await response.json()
            await self._event_queue.put(
                PriceTick(
                    source="binance_rest",
                    symbol=self._config.symbol,
                    price=float(payload["price"]),
                    stale_after_ms=self._config.binance.stale_after_ms,
                )
            )

    async def _run_coingecko(self, session: aiohttp.ClientSession) -> None:
        """Poll CoinGecko REST API."""
        if not self._config.coingecko.rest_url:
            return
        while True:
            try:
                async with session.get(self._config.coingecko.rest_url) as response:
                    response.raise_for_status()
                    payload = await response.json()
                    price = float(payload["bitcoin"]["usd"])
                    await self._event_queue.put(
                        PriceTick(
                            source="coingecko",
                            symbol=self._config.symbol,
                            price=price,
                            stale_after_ms=self._config.coingecko.stale_after_ms,
                        )
                    )
            except (aiohttp.ClientError, KeyError, ValueError, TypeError) as exc:
                self._logger.warning("external.coingecko_error", error=str(exc))
            await asyncio.sleep(self._config.coingecko.poll_interval_sec)

