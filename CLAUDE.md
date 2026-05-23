# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LLM-based automated BTC trading agent using LangGraph for multi-agent orchestration and OpenAI for decision-making. Trades on Upbit (Korean exchange) with paper trading support. Uses Binance Futures public data for derivatives sentiment and vision-based chart pattern recognition.

## Commands

```bash
# Install dependencies
uv sync --extra dev --extra dashboard

# Validate configuration
python -m trading.main --validate-only

# Run single trading cycle (paper trading)
python -m trading.main --mode single

# Run continuous trading (10-minute intervals by default)
python -m trading.main --mode continuous --interval 600

# Event-driven streaming mode (WebSocket + rule-based triggers)
python -m trading.main --streaming --cooldown 60

# Backtest
python -m trading.backtest.cli --days 30 --interval 300

# Dashboard (requires dashboard extra)
python -m trading.dashboard.app

# Run tests
pytest tests/ -v
pytest tests/test_core/test_hysteresis.py -v       # single file
pytest tests/test_core/test_hysteresis.py::test_name -v  # single test

# Linting and type checking
ruff check src/ tests/
mypy src/
```

## Architecture

### LangGraph Pipeline

Single linear graph in `src/trading/graph/builder.py` (`simple_pipeline`):

```
market → indicators → pattern → decision
                                   ↓
                       ┌───── HOLD ──────┐
                       ↓                 ↓
                      ops              risk → execution → ops → END
```

`route_after_decision` skips risk/execution for HOLD; `route_after_risk` skips execution when rejected.

### Key Components

- **`core/state.py`**: `TradingState` TypedDict schema shared across all agents
- **`core/time.py`**: Shared KST timezone constant
- **`agents/`**: Each agent has a class and a `*_node()` function for LangGraph integration
- **`adapters/upbit.py`**: `UpbitBrokerAdapter` with paper trading simulation
- **`adapters/binance_futures.py`**: Public Binance Futures data (OI, L/S ratios, funding rates) — no API key needed
- **`llm/client.py`**: `LLMClient` wrapper for OpenAI with JSON parsing and response cache
- **`config.py`**: Pydantic-settings configuration from `.env`
- **`graph/edges.py`**: Conditional edge logic (`route_after_decision`, `route_after_risk`, `route_after_execution`)

### TradingState Flow

The `TradingState` TypedDict accumulates data as it flows through the graph:
- `market`: Price, OHLCV, orderbook, volatility, 1h/24h change
- `mtf_ohlcv` / `mtf_trends`: Multi-timeframe (5m/1h/4h/1d) candles and alignment analysis
- `derivatives`: Binance Futures OI, L/S, funding rate
- `indicators`: Trend, momentum, RSI, MACD, Bollinger, OBV
- `trend_channel`: Regression channel slope, position, support/resistance
- `pattern_analysis`: Chart pattern (double bottom/top, H&S, etc.) with vision LLM
- `portfolio`: KRW balance, BTC balance, exposure, unrealized PnL
- `risk`: Daily loss %, position limits, kill switch
- `decision`: Action (BUY/SELL/HOLD), confidence, target_position_pct, position_delta_pct, status

### Decision Flow

1. **Rapid movement override** (`detect_rapid_movement`): bypasses LLM on 15min ≥1.5% / 30min ≥2% / 1h ≥3% moves
2. **LLM decision** (`_decide_with_llm`): uses cached HOLD decisions for similar market state. Cache key includes trend, momentum, RSI (5-unit bins), exposure (5%-unit bins), volatility, **funding_signal, position_bias, oi_trend** — so a derivatives shift invalidates an otherwise-identical entry.
3. **MTF trend alignment check** (`check_mtf_trend_alignment`): blocks LLM action if dominant trend disagrees, unless confidence ≥ 0.65 override
4. **Position sizing** (`PositionSizer`): confidence → target position % → delta; HOLD if delta below threshold
5. **Hysteresis** (`HysteresisManager`): blocks rapid BUY↔SELL reversals
6. **Daily trade cap** (`RiskManager.check_daily_trade_cap`): BUY rejected past `max_trades_per_day` (default 20). **SELL always allowed** — stop-loss exits are never throttled.
7. **Rule-based fallback**: 6-signal bullish/bearish count (trend, momentum, RSI, position_bias, funding_signal, OI_trend)

### Position Sizing (`core/position_sizing.py`)

Tiered confidence-to-position mapping: calculates target position % based on model confidence, then determines delta from current position. Trades only execute if delta exceeds minimum threshold.

### Isolated Balance Tracking (`core/isolated_balance.py`)

Sandboxed balance tracking for the bot's allocated capital (KRW spent, BTC acquired, available funds), independent from user's existing Upbit holdings. Allows the bot to operate within a dedicated budget.

**Operational safety contracts** (matter for live trading):
- Tracker records on `result.filled_quantity > 0` AND status in (FILLED, PARTIALLY_FILLED) — partial fills are NOT dropped (would otherwise leak balance vs. exchange).
- Skip recording when `result.average_price is None or ≤ 0` — prevents zero-cost-basis records that permanently break P&L. Logs an error so divergence is visible.
- `record_buy/sell` returns `False` on tracker-side insufficient balance — ExecutionAgent surfaces this as an error log (real exchange already moved; tracker has diverged and needs investigation).
- `_save()` writes via `tmp + fsync + os.replace()` — POSIX-atomic; readers never see a half-written JSON even on crash or concurrent write.
- Both `main.py` and `main_async.py` call `tracker.adjust_capital(settings.isolated_capital_krw)` on init so capital changes are honored across restarts. `--reset-isolated` is supported in both modes to wipe holdings back to initial capital.
- **Single-instance lock** (`isolated_balance.json.lock` via `fcntl.flock`): a second bot process trying to start with the same state file raises `RuntimeError` instead of corrupting the JSON. Lock auto-releases on process exit.
- **Daily P&L is midnight-rebased in KST**: `get_portfolio_value()` resets `daily_start_value` on each KST date change. RiskAgent uses this for `daily_pnl_pct` so the daily loss limit only triggers on today's drawdown, not cumulative loss on long-running bots.
- **All tracker timestamps in KST** (`+09:00` ISO suffix) for consistency with the rest of the system.
- In isolated mode, ExecutionAgent skips `broker.get_all_balances()` — the tracker's virtual balance is authoritative for sizing.

### Risk Management (`risk/`)

- **`limits.py`**: Enforces daily loss limits, position limits, min/max trade sizes
- **`validator.py`**: Validates LLM decisions against confidence thresholds and portfolio constraints; optional LLM secondary validation

### Event-Driven Mode (Streaming)

Two-layer architecture minimizing LLM costs:

```
Layer 1: Real-time monitoring (no LLM cost)
  WebSocket → MessageHandler → TriggerEvaluator → EventDispatcher

Layer 2: LLM decision (only when triggered)
  EventBatch → LangGraph pipeline → Decision/Execute
```

Trigger conditions (configurable in `triggers/conditions.py`):
- Price change: 1min ≥1%, 5min ≥2%, 24h ≥5%
- Volume spike: ≥5x average
- RSI extreme: ≤20 or ≥80

Cost controls: 60s cooldown between LLM calls, 10s event batching window, 300s post-trade cooldown.

### Indicators (`indicators/`)

- **`trend.py`**: EMA crossovers
- **`trend_channel.py`**: Regression-based channel (slope, support/resistance levels)
- **`momentum.py`**: RSI, MACD, OBV
- **`volatility.py`**: ATR, Bollinger Bands
- **`multi_timeframe.py`**: EMA-based trend alignment across 5m/1h/4h/1d timeframes for confidence adjustments

### Chart Pattern Recognition (`agents/pattern_agent.py`)

Vision-based LLM analysis (GPT-4o) triggered only on price change ≥1% (1h) / ≥2% (24h), high volatility, or Bollinger Band breakouts. Generates candlestick chart PNG via matplotlib, sends to vision model. Falls back to rule-based V-reversal / double-bottom/top detection.

### Anomaly Detection (`core/anomaly.py`)

Detects sudden price surges/drops, volume spikes, and volatility spikes with configurable thresholds and severity classification.

### History & Dashboard

Append-only JSONL recorders in `core/`:
- `decision_history.py`: BUY/SELL/HOLD decisions with confidence
- `indicator_history.py`: RSI, MACD, Bollinger, OBV snapshots
- `derivatives_history.py`: OI, L/S ratios, funding rates
- `history_reader.py`: Loads JSONL history across date ranges for the dashboard

Dashboard (`dashboard/app.py`): Streamlit UI displaying decisions, indicator charts, price movements, and derivatives sentiment with i18n support.

### Backtest Engine (`backtest/`)

Simulates trading on historical data with configurable fees/slippage. CLI in `backtest/cli.py` with parameters for days, interval, initial capital. Generates reports via `backtest/report.py` with metrics from `backtest/metrics.py`.

## LLM Call Frequency Controls

The bot makes LLM (OpenAI) calls only inside `DecisionAgent` and conditionally in `PatternAgent`. Frequency is shaped by three knobs:

| Knob | Default | Where | Purpose |
|---|---|---|---|
| Polling interval | **600s (10min)** | `main.py --interval` | Sleep between graph runs in polling mode |
| LLM cache TTL | **900s (15min)** | `settings.llm_cache_ttl_seconds` | Re-use HOLD decisions across cycles |
| Streaming cooldown | 60s | `settings.trigger_cooldown_seconds` | Min interval between LLM calls in streaming mode |

**Why TTL > polling interval**: a TTL shorter than the polling interval makes the cache expire between cycles, defeating the point. Default TTL is 15 min so cached HOLD decisions survive at least one full cycle.

**`--streaming` mode** applies the `HysteresisConfig` preset selected by `settings.hysteresis_mode` automatically (default `streaming`). Polling mode keeps a generic config and only patches `action_reversal_delta` from `--hysteresis-reversal-delta`.

**Cost vs signal-quality framing**: with `gpt-5-nano` the per-call cost is negligible; the real reason to throttle is to avoid repeated identical decisions on minor noise. Use streaming mode when you want fastest reaction with fewest LLM calls — rule-based triggers gate the LLM only on real volatility.

## Decision Hysteresis (`core/hysteresis.py`)

Prevents BUY↔SELL flip-flopping. For reversals, requires confidence delta ≥ threshold (default 0.35). Example: BUY@0.70 → SELL needs ≥1.05 confidence (blocked → converted to HOLD).

CLI flags: `--hysteresis-reversal-delta 0.4`, `--no-hysteresis`

## Environment Variables

Required in `.env`:
- `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY`: Upbit API credentials
- `OPENAI_API_KEY`: For LLM decision-making

Optional:
- `CMC_API_KEY`: CoinMarketCap for additional data
- `TRADING_MODE`: "paper" (default) or "live"
- `OPENAI_MODEL`: Default "gpt-4o-mini"
- `OPENAI_MODEL_VISION`: Default "gpt-4o" (for chart pattern recognition)
- `ISOLATED_MODE`, `ISOLATED_CAPITAL_KRW`: Sandboxed bot capital
- `TREND_MODE`: `fast` / `normal` / `slow` (EMA window selection)
- `HYSTERESIS_MODE`: `streaming` / `daily` / `conservative`
- `LLM_CACHE_TTL_SECONDS`: HOLD-decision cache TTL (default 900s, must exceed polling interval)
- `MAX_TRADES_PER_DAY`: Daily BUY cap (default 20). SELL is always allowed.

## Testing

Uses pytest with `pytest-asyncio` (`asyncio_mode = "auto"`). Paper trading mode auto-enabled in tests. Key fixtures in `tests/conftest.py`: `mock_upbit`, `mock_env`.

```bash
pytest tests/ -v
pytest tests/test_core/test_hysteresis.py -v
pytest --cov=src/trading tests/  # coverage
```
