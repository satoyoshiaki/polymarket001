# polymarket001

`polymarket001` は、Polymarket の BTC 短期市場向けに構築された asyncio ベースのイベント駆動型トレーディングシステムです。`backtest`、`paper`、`shadow_live`、`guarded_live` の4つの実行モードに対応しています。

## 前提条件

- Python 3.11 以上
- `pip` または PEP 517 対応のインストーラー
- guarded live モードを使用する場合は Polymarket API 認証情報

## インストール

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
```

## 環境変数の設定

`.env` に以下を設定してください：

- `POLYMARKET_API_KEY`
- `POLYMARKET_SECRET`
- `POLYMARKET_PASSPHRASE`
- `POLYMARKET_FUNDER_ADDRESS`
- `WEBHOOK_URL`
- `POLYMARKET_LIVE_ENABLED`

`POLYMARKET_LIVE_ENABLED` は、意図的に guarded live 実行を行う場合のみ `true` に設定してください。その際、`configs/live.yaml` の `live_trading_enabled: true` も同時に必要です。

## 実行モード

**バックテスト：**

```bash
python -m app.main --config configs/dev.yaml --backtest-file data/sample_backtest.csv
```

**ペーパートレード（デフォルト）：**

```bash
python -m app.main --config configs/paper.yaml
```

**シャドウライブ：**

```bash
python scripts/run_shadow.py
```

**Guarded ライブ（実注文）：**

```bash
POLYMARKET_LIVE_ENABLED=true python scripts/run_live.py
```

## 安全に関する注意事項

- `guarded_live` モードは、設定ファイルのフラグと環境変数の両方が明示的に有効になっていない限り起動を拒否します。
- レイテンシ・WebSocket 切断・フィル率・注文/キャンセルレート・時間/日次損失上限など、リスク制限はランタイムで強制されます。
- 実注文が可能な環境では、Reconciliation と Webhook アラートを必ず有効にしてください。
- **本システムは研究・検証目的で作成されています。実際の資金を使った運用は自己責任で行ってください。**

## アーキテクチャ概要

| ディレクトリ | 内容 |
|---|---|
| `app/clients` | Polymarket マーケットデータおよび外部 BTC 価格フィード |
| `app/engines` | 価格集約・シグナル生成・リスク管理・約定・バックテスト・PnL |
| `app/services` | マーケットマッピング・注文/ポジション管理・Reconciliation・ペーパーブローカー・メトリクス |
| `configs/` | 環境別 YAML 設定ファイル |
| `scripts/` | 各実行モードの起動スクリプト |
| `tests/` | ユニットテスト・インテグレーションテスト |

## リスク管理パラメータ

以下のパラメータはすべて設定ファイルから変更可能です：

| パラメータ | 説明 |
|---|---|
| `max_order_notional_pct` | 1注文の最大想定元本（ポートフォリオ比率） |
| `max_market_exposure_pct` | 1マーケットへの最大エクスポージャー |
| `max_daily_loss_pct` | 日次最大損失上限 |
| `max_hourly_loss_pct` | 時間次最大損失上限 |
| `max_open_orders` | 最大オープン注文数 |
| `max_orders_per_sec` | 秒間最大注文数 |
| `max_cancel_per_sec` | 秒間最大キャンセル数 |
| `latency_kill_switch_ms` | キルスイッチ発動レイテンシ閾値（ms） |
| `ws_disconnect_kill_after_sec` | WebSocket 切断後キルスイッチ発動までの秒数 |
| `min_fill_ratio` | 最低フィル率（下回るとキルスイッチ） |
| `max_error_rate_per_min` | 分間最大エラー率 |

## メトリクス

Prometheus メトリクスは `prometheus_client.start_http_server` 経由で `/metrics` に公開されます。主なメトリクス：`order_count`、`fill_count`、`pnl_usd`、`latency_ms`、`kill_switch_active`、`ws_reconnect_count`、`signal_count`、`error_rate`

## テスト実行

```bash
cd polymarket001
pytest
```
