"""Configuration models and loader."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.models import Mode


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    json: bool = True


class MetricsConfig(BaseModel):
    """Metrics configuration."""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 9108


class WebhookConfig(BaseModel):
    """Webhook alert configuration."""

    url: str | None = None
    timeout_sec: float = 5.0


class PolymarketConfig(BaseModel):
    """Polymarket connectivity settings."""

    websocket_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    rest_url: str = "https://clob.polymarket.com"
    chain_id: int = 137
    api_key: SecretStr | None = None
    secret: SecretStr | None = None
    passphrase: SecretStr | None = None
    funder_address: str | None = None
    reconnect_base_sec: float = 1.0
    reconnect_max_sec: float = 30.0
    snapshot_depth: int = 10


class ExternalSourceConfig(BaseModel):
    """External price source settings."""

    enabled: bool = True
    stale_after_ms: int = 5_000
    poll_interval_sec: float = 2.0
    websocket_url: str | None = None
    rest_url: str | None = None


class ExternalPriceConfig(BaseModel):
    """External price aggregation settings."""

    symbol: str = "BTCUSDT"
    trim_ratio: float = 0.1
    binance: ExternalSourceConfig = Field(
        default_factory=lambda: ExternalSourceConfig(
            websocket_url="wss://stream.binance.com:9443/ws/btcusdt@trade",
            rest_url="https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            poll_interval_sec=1.0,
            stale_after_ms=4_000,
        )
    )
    coingecko: ExternalSourceConfig = Field(
        default_factory=lambda: ExternalSourceConfig(
            rest_url="https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            poll_interval_sec=5.0,
            stale_after_ms=12_000,
        )
    )


class SignalConfig(BaseModel):
    """Signal engine thresholds."""

    default_size: float = 10.0
    taker_fee_estimate: float = 0.01
    slippage_estimate: float = 0.01
    execution_buffer: float = 0.005
    min_net_edge: float = 0.02
    ttl_ms: int = 2_000
    probability_band: float = 500.0


class RiskConfig(BaseModel):
    """Runtime risk controls."""

    max_order_notional_pct: float = 0.05
    max_market_exposure_pct: float = 0.2
    max_daily_loss_pct: float = 0.05
    max_hourly_loss_pct: float = 0.02
    max_open_orders: int = 25
    max_orders_per_sec: int = 5
    max_cancel_per_sec: int = 10
    latency_kill_switch_ms: float = 500.0
    ws_disconnect_kill_after_sec: float = 20.0
    min_fill_ratio: float = 0.2
    max_error_rate_per_min: float = 10.0
    base_capital_usd: float = 10_000.0


class ExecutionConfig(BaseModel):
    """Execution settings."""

    order_type: str = "FAK"
    retry_attempts: int = 3
    retry_backoff_sec: float = 0.5
    reconciliation_interval_sec: float = 60.0


class PaperBrokerConfig(BaseModel):
    """Paper broker simulation settings."""

    slippage_bps: float = 10.0
    fill_probability: float = 1.0


class MarketDefinition(BaseModel):
    """Single BTC binary market definition."""

    market_id: str
    description: str
    strike_price: float
    settlement_side: str = "above"
    enabled: bool = True


class AppConfig(BaseModel):
    """Top-level application config."""

    model_config = ConfigDict(extra="forbid")

    app_name: str = "polymarket001"
    mode: Mode = Mode.PAPER
    live_trading_enabled: bool = False
    log: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    external_prices: ExternalPriceConfig = Field(default_factory=ExternalPriceConfig)
    signal: SignalConfig = Field(default_factory=SignalConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    paper_broker: PaperBrokerConfig = Field(default_factory=PaperBrokerConfig)
    markets: list[MarketDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_live_guard(self) -> "AppConfig":
        """Ensure guarded live requires explicit config and env flags."""
        if self.mode == Mode.GUARDED_LIVE:
            env_flag = os.getenv("POLYMARKET_LIVE_ENABLED", "").lower() == "true"
            if not (self.live_trading_enabled and env_flag):
                raise ValueError(
                    "guarded_live requires live_trading_enabled=true and "
                    "POLYMARKET_LIVE_ENABLED=true"
                )
        return self


def load_config(config_path: str | Path) -> AppConfig:
    """Load YAML config merged with environment secrets."""
    load_dotenv()
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    polymarket = raw.setdefault("polymarket", {})
    polymarket["api_key"] = os.getenv("POLYMARKET_API_KEY")
    polymarket["secret"] = os.getenv("POLYMARKET_SECRET")
    polymarket["passphrase"] = os.getenv("POLYMARKET_PASSPHRASE")
    polymarket["funder_address"] = os.getenv("POLYMARKET_FUNDER_ADDRESS")

    webhook = raw.setdefault("webhook", {})
    webhook["url"] = os.getenv("WEBHOOK_URL", webhook.get("url"))

    return AppConfig.model_validate(raw)


def dumpable_config(config: AppConfig) -> dict[str, Any]:
    """Return a redacted config for logging."""
    payload = config.model_dump(mode="json")
    for key in ("api_key", "secret", "passphrase"):
        if payload["polymarket"].get(key):
            payload["polymarket"][key] = "***"
    return payload

