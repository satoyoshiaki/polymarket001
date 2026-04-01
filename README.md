# polymarket001

`polymarket001` is an asyncio-based, event-driven BTC short-term market trading system for Polymarket with four run modes: `backtest`, `paper`, `shadow_live`, and `guarded_live`.

## Prerequisites

- Python 3.11+
- `pip` or another PEP 517-compatible installer
- Polymarket API credentials for guarded live trading

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
```

## Configure Environment

Populate `.env` with:

- `POLYMARKET_API_KEY`
- `POLYMARKET_SECRET`
- `POLYMARKET_PASSPHRASE`
- `POLYMARKET_FUNDER_ADDRESS`
- `WEBHOOK_URL`
- `POLYMARKET_LIVE_ENABLED`

`POLYMARKET_LIVE_ENABLED` must remain `false` unless you intentionally want guarded live execution and have also set `live_trading_enabled: true` in `configs/live.yaml`.

## Run Modes

Backtest:

```bash
python -m app.main --config configs/dev.yaml --backtest-file data/sample_backtest.csv
```

Paper:

```bash
python -m app.main --config configs/paper.yaml
```

Shadow live:

```bash
python scripts/run_shadow.py
```

Guarded live:

```bash
POLYMARKET_LIVE_ENABLED=true python scripts/run_live.py
```

## Safety Warnings

- `guarded_live` will refuse to start unless both the config flag and environment flag are explicitly enabled.
- Risk limits are enforced at runtime, including latency, websocket disconnect, fill ratio, order/cancel rate, and hourly/daily loss limits.
- Reconciliation and webhook alerts should remain enabled in any environment that can place live orders.

## Architecture Overview

- `app/clients`: Polymarket market data and external BTC price feeds
- `app/engines`: price aggregation, signal generation, risk, execution, backtest, and PnL
- `app/services`: market mapping, order/position management, reconciliation, paper brokerage, and metrics
- `configs/`: environment-specific YAML configs
- `scripts/`: convenience launchers for each run mode
- `tests/`: unit and integration coverage for the main trading path

## Metrics

Prometheus metrics are exposed on `/metrics` via `prometheus_client.start_http_server`. Key metrics include `order_count`, `fill_count`, `pnl_usd`, `latency_ms`, `kill_switch_active`, `ws_reconnect_count`, `signal_count`, and `error_rate`.

