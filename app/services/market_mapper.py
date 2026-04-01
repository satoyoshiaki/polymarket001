"""Market metadata lookup."""

from __future__ import annotations

from app.config import MarketDefinition


class MarketMapper:
    """Expose Polymarket market metadata used by the strategy."""

    def __init__(self, markets: list[MarketDefinition]) -> None:
        self._markets = {market.market_id: market for market in markets if market.enabled}

    def market_ids(self) -> list[str]:
        """Return enabled market ids."""
        return list(self._markets)

    def get_market(self, market_id: str) -> MarketDefinition | None:
        """Return a market definition by id."""
        return self._markets.get(market_id)

