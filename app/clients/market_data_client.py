"""Polymarket market data client."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import aiohttp
import structlog

from app.config import PolymarketConfig
from app.models import MarketSnapshot, TradeEvent, utc_now


class MarketDataClient:
    """Stream Polymarket market data and emit typed events."""

    def __init__(
        self,
        config: PolymarketConfig,
        market_ids: list[str],
        event_queue: asyncio.Queue[MarketSnapshot | TradeEvent],
    ) -> None:
        self._config = config
        self._market_ids = market_ids
        self._event_queue = event_queue
        self._logger = structlog.get_logger(__name__)
        self._session: aiohttp.ClientSession | None = None
        self._last_message_at: datetime = utc_now()
        self._reconnect_count = 0

    @property
    def last_message_at(self) -> datetime:
        """Return the last received timestamp."""
        return self._last_message_at

    @property
    def reconnect_count(self) -> int:
        """Return the reconnect count."""
        return self._reconnect_count

    async def run(self) -> None:
        """Run the websocket loop with reconnect backoff."""
        backoff = self._config.reconnect_base_sec
        async with aiohttp.ClientSession() as session:
            self._session = session
            while True:
                try:
                    await self._stream(session)
                    backoff = self._config.reconnect_base_sec
                except aiohttp.ClientError as exc:
                    self._reconnect_count += 1
                    self._logger.warning("market_data.ws_error", error=str(exc), backoff=backoff)
                    await self._refresh_snapshots()
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, self._config.reconnect_max_sec)
                except asyncio.CancelledError:
                    raise

    async def _stream(self, session: aiohttp.ClientSession) -> None:
        """Connect to websocket and process messages."""
        async with session.ws_connect(self._config.websocket_url, heartbeat=20) as websocket:
            await websocket.send_json(
                {
                    "assets_ids": self._market_ids,
                    "type": "market",
                }
            )
            self._logger.info("market_data.connected", market_ids=self._market_ids)
            await self._refresh_snapshots()
            async for message in websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    self._last_message_at = utc_now()
                    await self._handle_message(message.data)
                elif message.type == aiohttp.WSMsgType.ERROR:
                    raise aiohttp.ClientError("websocket message error")

    async def _handle_message(self, raw_message: str) -> None:
        """Parse a raw websocket message."""
        payload = json.loads(raw_message)
        if isinstance(payload, list):
            for item in payload:
                await self._decode_event(item)
            return
        await self._decode_event(payload)

    async def _decode_event(self, payload: dict[str, Any]) -> None:
        """Convert raw payloads into internal events."""
        event_type = str(payload.get("event_type") or payload.get("type") or "").lower()
        market_id = str(payload.get("asset_id") or payload.get("market") or payload.get("market_id") or "")
        if not market_id:
            return

        if "book" in event_type or {"best_bid", "best_ask"} <= payload.keys():
            snapshot = MarketSnapshot(
                market_id=market_id,
                best_bid=float(payload.get("best_bid", payload.get("bid", 0.0))),
                best_ask=float(payload.get("best_ask", payload.get("ask", 1.0))),
                last_trade_price=(
                    float(payload["price"]) if payload.get("price") is not None else None
                ),
                sequence=int(payload["sequence"]) if payload.get("sequence") is not None else None,
                timestamp=self._parse_timestamp(payload.get("timestamp")),
            )
            await self._event_queue.put(snapshot)
        elif "trade" in event_type or payload.get("price") is not None:
            trade = TradeEvent(
                market_id=market_id,
                price=float(payload["price"]),
                size=float(payload.get("size", payload.get("amount", 0.0))),
                side=str(payload.get("side", "buy")).lower(),
                trade_id=str(payload.get("id", payload.get("trade_id", ""))) or None,
                timestamp=self._parse_timestamp(payload.get("timestamp")),
            )
            await self._event_queue.put(trade)

    async def _refresh_snapshots(self) -> None:
        """Fetch REST snapshots after reconnects."""
        if self._session is None:
            return
        for market_id in self._market_ids:
            try:
                async with self._session.get(
                    f"{self._config.rest_url}/book",
                    params={"market": market_id, "depth": self._config.snapshot_depth},
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
                    bids = payload.get("bids", [])
                    asks = payload.get("asks", [])
                    if not bids or not asks:
                        continue
                    snapshot = MarketSnapshot(
                        market_id=market_id,
                        best_bid=float(bids[0]["price"]),
                        best_ask=float(asks[0]["price"]),
                        sequence=int(payload["sequence"]) if payload.get("sequence") else None,
                    )
                    await self._event_queue.put(snapshot)
            except (aiohttp.ClientError, KeyError, ValueError, TypeError) as exc:
                self._logger.warning("market_data.snapshot_failed", market_id=market_id, error=str(exc))

    def _parse_timestamp(self, raw_value: Any) -> datetime:
        """Parse provider timestamps with a UTC fallback."""
        if raw_value is None:
            return utc_now()
        if isinstance(raw_value, (int, float)):
            return datetime.fromtimestamp(float(raw_value) / 1000.0, tz=UTC)
        if isinstance(raw_value, str):
            try:
                return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            except ValueError:
                return utc_now()
        return utc_now()

