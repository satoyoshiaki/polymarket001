"""Shared typed contracts for the trading system."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


class Mode(str, Enum):
    """Supported application run modes."""

    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW_LIVE = "shadow_live"
    GUARDED_LIVE = "guarded_live"


class Side(str, Enum):
    """Trading side."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Supported order types."""

    GTC = "GTC"
    GTD = "GTD"
    FOK = "FOK"
    FAK = "FAK"


class OrderState(str, Enum):
    """Internal order lifecycle states."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class EventBase(BaseModel):
    """Base class for timestamped events."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    timestamp: datetime = Field(default_factory=utc_now)


class MarketSnapshot(EventBase):
    """Order book snapshot for a market."""

    market_id: str
    best_bid: float
    best_ask: float
    last_trade_price: float | None = None
    sequence: int | None = None

    @property
    def mid_price(self) -> float:
        """Return the midpoint price."""
        return (self.best_bid + self.best_ask) / 2.0


class TradeEvent(EventBase):
    """Market trade update."""

    market_id: str
    price: float
    size: float
    side: Side
    trade_id: str | None = None


class PriceTick(EventBase):
    """External reference price update."""

    source: str
    symbol: str
    price: float
    stale_after_ms: int

    def is_stale(self, now: datetime | None = None) -> bool:
        """Return whether the price tick is stale."""
        current = now or utc_now()
        age_ms = (current - self.timestamp).total_seconds() * 1000.0
        return age_ms > self.stale_after_ms


class ReferencePrice(EventBase):
    """Aggregated external reference price."""

    symbol: str
    price: float
    contributors: list[str]


class Signal(EventBase):
    """Execution signal produced by the signal engine."""

    market_id: str
    side: Side
    size: float
    raw_edge: float
    net_edge: float
    ttl_ms: int

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return whether the signal is expired."""
        current = now or utc_now()
        age_ms = (current - self.timestamp).total_seconds() * 1000.0
        return age_ms > self.ttl_ms


class OrderRequest(BaseModel):
    """Order submission request."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    market_id: str
    side: Side
    size: float
    price: float
    order_type: OrderType
    client_order_id: str
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderRecord(EventBase):
    """In-memory order record."""

    order_id: str
    client_order_id: str
    market_id: str
    side: Side
    size: float
    price: float
    order_type: OrderType
    state: OrderState = OrderState.PENDING
    filled_size: float = 0.0
    average_fill_price: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FillEvent(EventBase):
    """Normalized fill event."""

    order_id: str
    client_order_id: str
    market_id: str
    side: Side
    size: float
    price: float
    fee: float = 0.0


class Position(BaseModel):
    """Position state for a single market."""

    model_config = ConfigDict(extra="forbid")

    market_id: str
    quantity: float = 0.0
    average_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class ReconcileResult(BaseModel):
    """Outcome of a reconciliation cycle."""

    model_config = ConfigDict(extra="forbid")

    discrepancies: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=utc_now)


class RiskDecision(BaseModel):
    """Risk evaluation output."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str | None = None

